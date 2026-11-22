import { NativeSelect, TextInput } from '@mantine/core'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { type FormEvent, useRef, useState } from 'react'

import { api, ApiFailure, type Schemas, unwrap } from '../../api/client'
import { FormProblems } from '../../components/FormProblems'
import { Banner } from '../../components/layout'
import { Placeholder } from '../../components/Placeholder'
import { calendarDate, lbp } from '../../format'
import { errorMessage, strings } from '../../strings/en'
import { saveFile, SEARCH_MAX, sendStockFile, usePharmacy, useStock, useWaitingUpload, type Zone } from './data'
import { BATCH_MAX, batchFits, tidyBatch } from './draft'

const s = strings.pharmacy.stock
const u = strings.pharmacy.upload

type Item = Schemas['StockItem']
type Upload = Schemas['StockUpload']

const ZONES: (Zone | null)[] = [null, 'NEAR_EXPIRY', 'EARLY_RELEASE', 'PRIVATE', 'EXPIRED']
const TONE: Record<Item['zone'], string> = {
  NEAR_EXPIRY: 'green',
  EARLY_RELEASE: 'blue',
  PRIVATE: 'grey',
  EXPIRED: 'red',
  NOT_ELIGIBLE: 'red',
}

function codeOf(error: unknown): string {
  return error instanceof ApiFailure ? error.code : 'INTERNAL_ERROR'
}

/**
 * PS-6: the pharmacy's whole stock. Private: only the pharmacy sees it. The two ways to
 * change it, a file and one box by hand, come first: under a table of 50 rows a box
 * typed by hand was about 60 keyboard stops away.
 */
export function InventoryPage() {
  return (
    <main className="portal__main">
      <h1 className="page-title">{strings.pharmacy.inventory}</h1>
      <StockFile />
      <AddBox />
      <StockTable />
    </main>
  )
}

/**
 * A stock file, in two steps: it is read and summarised, and nothing changes until
 * [Apply] (SM-4). The file is the whole stock: what it doesn't name is set to 0.
 */
function StockFile() {
  const queryClient = useQueryClient()
  const waiting = useWaitingUpload()
  const picker = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState<string | null>(null)
  const [applied, setApplied] = useState(false)
  const upload = waiting.data?.upload ?? null

  async function run(action: () => Promise<unknown>, done = false) {
    setBusy(true)
    setFailed(null)
    setApplied(false)
    try {
      await action()
      setApplied(done)
      await queryClient.invalidateQueries({ queryKey: ['pharmacy'] })
    } catch (error) {
      const reason = error instanceof ApiFailure ? error.details.reason : null
      setFailed(
        typeof reason === 'string' && codeOf(error) === 'UPLOAD_FAILED'
          ? u.failed(reason)
          : errorMessage(codeOf(error)),
      )
    } finally {
      setBusy(false)
      if (picker.current) picker.current.value = ''
    }
  }

  return (
    <section className="panel" aria-labelledby="stock-file">
      <h2 id="stock-file" className="panel__title">
        {u.title}
      </h2>
      <ol className="plain-steps">
        {u.steps.map((step) => (
          <li key={step}>{step}</li>
        ))}
      </ol>
      <span className="hint">{u.expiryHint}</span>
      <span className="hint">{u.replaceHint}</span>
      <span className="hint">{u.codeHint}</span>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
        <button
          type="button"
          className="pill-button pill-button--grey"
          onClick={() =>
            void run(() => saveFile('/api/v1/pharmacy/inventory/template', 'dawalink-stock-template.csv'))
          }
        >
          {u.template}
        </button>
        <label className="pill-button file-button">
          {u.choose}
          <input
            ref={picker}
            type="file"
            className="sr-only"
            accept=".csv,text/csv"
            disabled={busy}
            onChange={(event) => {
              const file = event.currentTarget.files?.[0]
              if (file) void run(() => sendStockFile(file))
            }}
          />
        </label>
      </div>
      <div role="status" aria-live="polite" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {busy && <span className="soft">{u.reading}</span>}
        {failed && <Banner tone="red">{failed}</Banner>}
        {applied && <Banner tone="green">{u.applied}</Banner>}
        {upload && !busy && (
          <UploadSummary
            upload={upload}
            onApply={() =>
              void run(
                () =>
                  unwrap(
                    api.POST('/api/v1/pharmacy/inventory/uploads/{upload_id}/apply', {
                      params: { path: { upload_id: upload.id } },
                    }),
                  ),
                true,
              )
            }
            onDiscard={() =>
              void run(() =>
                unwrap(
                  api.POST('/api/v1/pharmacy/inventory/uploads/{upload_id}/discard', {
                    params: { path: { upload_id: upload.id } },
                  }),
                ),
              )
            }
            onErrors={() =>
              void run(() =>
                saveFile(
                  '/api/v1/pharmacy/inventory/uploads/{upload_id}/errors.csv',
                  'dawalink-stock-errors.csv',
                  upload.id,
                ),
              )
            }
          />
        )}
      </div>
    </section>
  )
}

const PROBLEMS_SHOWN = 5

function UploadSummary({
  upload,
  onApply,
  onDiscard,
  onErrors,
}: {
  upload: Upload
  onApply: () => void
  onDiscard: () => void
  onErrors: () => void
}) {
  const zeroed = upload.summary.zeroed
  const tiles: { label: string; count: number; danger?: boolean }[] = [
    { label: u.tiles.ready, count: upload.rows_ok },
    { label: u.tiles.fix, count: upload.rows_error },
    { label: u.tiles.new, count: upload.summary.new },
    // The one count that takes stock away: red when it isn't nothing (R-U2).
    { label: u.tiles.zeroed, count: zeroed, danger: zeroed > 0 },
  ]
  return (
    <div className="row-card" style={{ background: 'var(--page)' }}>
      <span style={{ fontWeight: 600 }}>{u.waiting(upload.file_name)}</span>
      <div role="group" aria-label={u.tilesLabel}>
        <dl className="upload-tiles">
          {tiles.map((tile) => (
            <div key={tile.label} className={`upload-tile${tile.danger ? ' upload-tile--red' : ''}`}>
              <dt>{tile.label}</dt>
              <dd>{tile.count}</dd>
            </div>
          ))}
        </dl>
      </div>
      {upload.summary.changed > 0 && <span className="soft">{u.changedLine(upload.summary.changed)}</span>}
      {/* A refused row is never read, so its box counts as missing from the file and is
          set to 0 with the others: said before [Apply], in red. */}
      {upload.rows_error > 0 && zeroed > 0 && (
        <Banner tone="red" alert>
          {u.zeroedWarning}
        </Banner>
      )}
      {upload.summary.reserved_kept > 0 && (
        <Banner tone="amber">{u.reservedKept(upload.summary.reserved_kept)}</Banner>
      )}
      {upload.summary.left_alone > 0 && (
        <Banner tone="amber">{u.leftAlone(upload.summary.left_alone)}</Banner>
      )}
      {upload.errors.length > 0 && (
        <>
          <span className="hint">{u.problems}</span>
          <ul className="plain-list">
            {upload.errors.slice(0, PROBLEMS_SHOWN).map((error) => (
              <li key={error.row} style={{ fontSize: 15 }}>
                <strong>{u.row(error.row)}</strong> · {error.product}: {error.problem}
                {error.did_you_mean.length > 0 && ` · ${u.didYouMean(error.did_you_mean.join(', '))}`}
              </li>
            ))}
          </ul>
          {upload.rows_error > PROBLEMS_SHOWN && (
            <span className="hint">{u.moreProblems(upload.rows_error - PROBLEMS_SHOWN)}</span>
          )}
          <button type="button" className="text-button" style={{ alignSelf: 'flex-start', padding: 0 }} onClick={onErrors}>
            {u.errorsFile}
          </button>
        </>
      )}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
        <button type="button" className="pill-button" disabled={upload.rows_ok === 0} onClick={onApply}>
          {u.applyRows(upload.rows_ok)}
        </button>
        <button type="button" className="pill-button pill-button--grey" onClick={onDiscard}>
          {u.discard}
        </button>
      </div>
    </div>
  )
}

function StockTable() {
  const [zone, setZone] = useState<Zone | null>(null)
  const [typed, setTyped] = useState('')
  const stock = useStock(zone, typed.trim())
  const items = stock.items
  return (
    <section className="panel" aria-labelledby="stock">
      <div>
        <h2 id="stock" className="panel__title">
          {s.title}
        </h2>
        <span className="hint">{s.private}</span>
      </div>
      <TextInput
        label={s.search}
        size="md"
        maxLength={SEARCH_MAX}
        value={typed}
        onChange={(event) => setTyped(event.currentTarget.value)}
      />
      <div className="chips" role="group" aria-label={s.zone}>
        {ZONES.map((choice) => (
          <button
            key={choice ?? 'ALL'}
            type="button"
            className="chip"
            aria-pressed={zone === choice}
            onClick={() => setZone(choice)}
          >
            {s.zones[choice ?? 'ALL']}
          </button>
        ))}
      </div>
      {stock.pending && <Placeholder height={56} />}
      {stock.loaded && items.length === 0 && (
        <span className="soft">{typed.trim() || zone ? s.noneFound : s.none}</span>
      )}
      {items.length > 0 && (
        // A wide table scrolls sideways on a phone: the region is reachable by keyboard.
        // The medicine's column stays in place, so a quantity is never edited without
        // its name in view, and the right edge fades to show there is more.
        <div className="table-scroll table-scroll--fade" role="region" aria-label={s.table} tabIndex={0}>
          <table className="stock-table stock-table--pinned">
            <thead>
              <tr>
                <th scope="col">{s.product}</th>
                <th scope="col">{s.batch}</th>
                <th scope="col">{s.expiry}</th>
                <th scope="col">{s.inStock}</th>
                <th scope="col">{s.reserved}</th>
                <th scope="col">{s.zone}</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <StockRow key={item.id} item={item} />
              ))}
            </tbody>
          </table>
        </div>
      )}
      {stock.hasMore && (
        <button type="button" className="text-button" onClick={stock.more}>
          {s.more}
        </button>
      )}
    </section>
  )
}

/** One box. Its quantity is corrected in place, after a sale in the shop (PF-2). */
function StockRow({ item }: { item: Item }) {
  const queryClient = useQueryClient()
  const [typed, setTyped] = useState<string | null>(null)
  const [note, setNote] = useState<{ tone: 'amber' | 'red'; text: string } | null>(null)
  const value = typed ?? String(item.qty_on_hand)
  const changed = typed !== null && typed !== String(item.qty_on_hand) && /^\d+$/.test(typed)

  async function save(event: FormEvent) {
    event.preventDefault()
    if (!changed) return
    setNote(null)
    try {
      const done = await unwrap(
        api.PATCH('/api/v1/pharmacy/inventory/items/{item_id}', {
          params: { path: { item_id: item.id } },
          body: { qty_on_hand: Number(typed) },
        }),
      )
      setTyped(null)
      if (done.reserved_kept) setNote({ tone: 'amber', text: s.reservedKept(done.item.qty_reserved) })
      await queryClient.invalidateQueries({ queryKey: ['pharmacy'] })
    } catch (error) {
      setNote({ tone: 'red', text: errorMessage(codeOf(error)) })
    }
  }

  const status =
    item.zone !== 'NEAR_EXPIRY'
      ? s.zoneOf[item.zone]
      : item.paused
        ? s.paused
        : item.held_back
          ? s.heldBack
          : item.qty_available === 0
            ? s.outOfStock
            : item.listed_by_hand
              ? s.listedByYou
              : s.zoneOf.NEAR_EXPIRY
  return (
    <>
      <tr>
        <th scope="row">
          {item.product.name}
          {item.product.strength && <span className="hint"> · {item.product.strength}</span>}
        </th>
        <td>{item.batch}</td>
        <td>
          {calendarDate(item.expiry_date)}
          <span className="hint"> · {s.daysLeft(item.days_left)}</span>
        </td>
        <td>
          <form onSubmit={save} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <input
              className="quantity-input"
              type="text"
              inputMode="numeric"
              aria-label={s.quantityOf(item.product.name, item.batch)}
              // As the add form: never more than the API takes (A#35).
              maxLength={QUANTITY_DIGITS}
              value={value}
              onChange={(event) => setTyped(event.currentTarget.value.replace(/\D/g, ''))}
            />
            {changed && (
              <button type="submit" className="text-button" style={{ padding: 0 }}>
                {s.saveQuantity}
              </button>
            )}
          </form>
        </td>
        <td>{item.qty_reserved}</td>
        <td>
          <span className={`status-pill status-pill--${item.visible ? 'green' : item.zone === 'NEAR_EXPIRY' ? 'amber' : TONE[item.zone]}`}>
            {status}
          </span>
        </td>
      </tr>
      {note && (
        <tr>
          <td colSpan={6}>
            <Banner tone={note.tone}>{note.text}</Banner>
          </td>
        </tr>
      )}
    </>
  )
}

/** A medicine as the Ministry lists it. The same name and strength can be listed
 * several times, for other packs or makers: the pack and the public price tell them
 * apart, and the code is what a stock file writes to say which one it means. */
function fullName(product: Schemas['ProductSummary']): string {
  const parts = [product.name, product.strength, product.form, product.pack]
  return `${parts.filter(Boolean).join(' · ')} · ${lbp(product.public_price.lbp)} · ${s.add.code(product.code)}`
}

/** How many years ahead a box's expiry can be chosen: a box rarely lasts longer. */
const EXPIRY_YEARS = 6
/** The most packs typed for one box: five digits stay under the API's own bound. */
const QUANTITY_DIGITS = 5

const two = (value: number) => String(value).padStart(2, '0')

/**
 * A box prints a month and a year, and DawaLink counts it until the last day of that
 * month (R-D6). Written as text, never through a `Date` and `toISOString`, which would
 * move the day with the computer's time zone.
 */
function lastDayOf(year: number, month: number): string {
  const days = new Date(Date.UTC(year, month, 0)).getUTCDate()
  return `${year}-${two(month)}-${two(days)}`
}

/** What the pharmacist is told once the box is added: whether clients see it now. */
function addedText(item: Item, rule: number): string {
  const a = s.add
  const name = item.product.name
  if (item.visible) return a.addedVisible(name, item.batch)
  if (item.zone === 'NEAR_EXPIRY') return a.addedHeld(name, item.batch, rule)
  if (item.zone === 'NOT_ELIGIBLE') return a.addedNotListed(name, item.batch)
  return a.addedPrivate(name, item.batch)
}

/** One box typed by hand, with the medicine chosen from the catalog (PS-6). */
function AddBox() {
  const a = s.add
  const queryClient = useQueryClient()
  const pharmacy = usePharmacy()
  const [typed, setTyped] = useState('')
  const [product, setProduct] = useState<Schemas['ProductSummary'] | null>(null)
  const [batch, setBatch] = useState('')
  const [month, setMonth] = useState('')
  const [year, setYear] = useState('')
  const [quantity, setQuantity] = useState('')
  const [tried, setTried] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const [refusedBatch, setRefusedBatch] = useState(false)
  const [state, setState] = useState<{ tone: 'green' | 'red'; text: string } | null>(null)
  const wanted = typed.trim()
  const found = useQuery({
    queryKey: ['catalog', wanted],
    queryFn: () =>
      unwrap(api.GET('/api/v1/catalog/products', { params: { query: { q: wanted, limit: 6 } } })),
    enabled: product === null && wanted.length >= 2,
  })

  // The app's day, not the computer's: the demo clock moves it (R-T11).
  const today = (pharmacy.data?.server_now ?? '').slice(0, 10)
  const thisYear = Number(today.slice(0, 4)) || 0
  const expiry = month && year ? lastDayOf(Number(year), Number(month)) : ''
  const problems = {
    product: product ? null : a.problems.product,
    batch: !batch.trim() ? a.problems.batch : batchFits(batch) ? null : a.problems.batchRule(BATCH_MAX),
    expiry: !expiry ? a.problems.expiry : today && expiry < today ? a.problems.expired : null,
    quantity: /^\d+$/.test(quantity) && Number(quantity) >= 1 ? null : a.problems.quantity,
  }
  const shown = (field: keyof typeof problems) => (tried && problems[field]) || null
  const batchError = shown('batch') || (refusedBatch ? a.problems.batchRule(BATCH_MAX) : null)
  const marked =
    (['product', 'expiry', 'quantity'] as const).filter((field) => shown(field)).length +
    (batchError ? 1 : 0)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setTried(true)
    setRefusedBatch(false)
    setState(null)
    if (!product || Object.values(problems).some(Boolean)) {
      setAttempt((count) => count + 1)
      return
    }
    try {
      const item = await unwrap(
        api.POST('/api/v1/pharmacy/inventory/items', {
          body: {
            product_id: product.id,
            batch: tidyBatch(batch),
            expiry_date: expiry,
            qty: Number(quantity),
          },
        }),
      )
      setProduct(null)
      setTyped('')
      setBatch('')
      setMonth('')
      setYear('')
      setQuantity('')
      setTried(false)
      setState({ tone: 'green', text: addedText(item, pharmacy.data?.auto_list_days ?? 0) })
      await queryClient.invalidateQueries({ queryKey: ['pharmacy'] })
    } catch (error) {
      // The API checks the batch's shape (domain/pharmacy_details.py): said on the field.
      if (error instanceof ApiFailure && error.details.field === 'batch') {
        setRefusedBatch(true)
        setAttempt((count) => count + 1)
      } else {
        setState({ tone: 'red', text: errorMessage(codeOf(error)) })
      }
    }
  }

  return (
    <section className="panel" aria-labelledby="add-box">
      <h2 id="add-box" className="panel__title">
        {a.title}
      </h2>
      <form className="form" onSubmit={submit} noValidate>
        {product ? (
          <div className="row-card__top">
            <span style={{ fontWeight: 600 }}>{fullName(product)}</span>
            <button type="button" className="text-button" onClick={() => setProduct(null)}>
              {a.change}
            </button>
          </div>
        ) : (
          <>
            <TextInput
              label={a.product}
              description={a.productHint}
              size="md"
              autoComplete="off"
              maxLength={SEARCH_MAX}
              value={typed}
              onChange={(event) => setTyped(event.currentTarget.value)}
              error={shown('product')}
            />
            <div role="status" aria-live="polite" className="chips">
              {(found.data?.items ?? []).map((row) => (
                <button
                  key={row.id}
                  type="button"
                  className="chip"
                  aria-label={a.choose(fullName(row))}
                  onClick={() => setProduct(row)}
                >
                  {fullName(row)}
                </button>
              ))}
              {found.isSuccess && found.data.items.length === 0 && (
                <span className="hint">{a.noneFound}</span>
              )}
            </div>
          </>
        )}
        <TextInput
          label={a.batch}
          size="md"
          autoComplete="off"
          maxLength={BATCH_MAX}
          value={batch}
          onChange={(event) => {
            setBatch(event.currentTarget.value)
            setRefusedBatch(false)
          }}
          error={batchError}
        />
        <fieldset className="choice">
          <legend>{a.expiry}</legend>
          <span className="hint">{a.expiryHint}</span>
          <div className="field-row">
            <NativeSelect
              label={a.expiryMonth}
              size="md"
              value={month}
              onChange={(event) => setMonth(event.currentTarget.value)}
              error={shown('expiry') && !month ? true : undefined}
              data={[
                { value: '', label: '' },
                ...a.months.map((name, index) => ({
                  value: String(index + 1),
                  label: `${two(index + 1)} · ${name}`,
                })),
              ]}
            />
            <NativeSelect
              label={a.expiryYear}
              size="md"
              value={year}
              onChange={(event) => setYear(event.currentTarget.value)}
              error={shown('expiry') && (!year || Boolean(month)) ? true : undefined}
              data={[
                { value: '', label: '' },
                ...Array.from({ length: thisYear ? EXPIRY_YEARS : 0 }, (_, index) => {
                  const value = String(thisYear + index)
                  return { value, label: value }
                }),
              ]}
            />
          </div>
          {shown('expiry') && <span className="field-problem">{shown('expiry')}</span>}
        </fieldset>
        <TextInput
          label={a.quantity}
          size="md"
          inputMode="numeric"
          maxLength={QUANTITY_DIGITS}
          value={quantity}
          onChange={(event) => setQuantity(event.currentTarget.value.replace(/\D/g, ''))}
          error={shown('quantity')}
        />
        <div role="status" aria-live="polite">
          {state && <Banner tone={state.tone}>{state.text}</Banner>}
        </div>
        <FormProblems count={marked} attempt={attempt} />
        <button type="submit" className="pill-button" style={{ alignSelf: 'flex-start' }}>
          {a.submit}
        </button>
      </form>
    </section>
  )
}
