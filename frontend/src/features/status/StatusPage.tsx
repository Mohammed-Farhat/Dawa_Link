import { Badge, Button, Card, Container, Group, Paper, Stack, Text, Title } from '@mantine/core'

import { strings } from '../../strings/en'
import { useHealth } from './useHealth'

const s = strings.status

type PartState = 'running' | 'checking' | 'down'

function PartRow({ name, state, detail }: { name: string; state: PartState; detail?: string }) {
  const label = { running: s.running, checking: s.checking, down: s.notReachable }[state]
  // Text on its own tint: the pairs docs/11 §2.1 checks for contrast.
  const [background, text] = {
    running: ['green.0', 'green.7'],
    checking: ['ink.1', 'ink.7'],
    down: ['red.0', 'red.7'],
  }[state]
  return (
    <Group justify="space-between" wrap="nowrap">
      <div>
        <Text fw={600}>{name}</Text>
        {detail && (
          <Text size="sm" c="ink.7">
            {detail}
          </Text>
        )}
      </div>
      <Badge color={background} c={text} size="lg" radius="xl" tt="none" fz={13} fw={600}>
        {label}
      </Badge>
    </Group>
  )
}

function Notice({ tone, children }: { tone: 'good' | 'bad'; children: string }) {
  const [background, text] = tone === 'good' ? ['green.0', 'green.7'] : ['red.0', 'red.7']
  return (
    <Paper bg={background} c={text} p="md" radius="lg" fw={500}>
      {children}
    </Paper>
  )
}

/** The skeleton's only screen. The real Home (CS-5) replaces it when the client portal is built. */
export function StatusPage() {
  const health = useHealth()

  const apiState: PartState = health.isPending ? 'checking' : health.isError ? 'down' : 'running'
  const databaseState: PartState = health.isPending
    ? 'checking'
    : health.data?.db === 'ok'
      ? 'running'
      : 'down'

  return (
    <Container size="xs" py="xl">
      <Stack gap="lg">
        <div>
          <Text fw={700} c="blue.6">
            {strings.appName}
          </Text>
          <Title order={1} size={26}>
            {s.title}
          </Title>
          <Text c="ink.7">{s.intro}</Text>
        </div>

        <Card radius="lg" padding="lg" withBorder={false}>
          <Stack gap="md">
            <PartRow name={s.website} state="running" />
            <PartRow
              name={s.api}
              state={apiState}
              detail={health.data ? s.version(health.data.version) : undefined}
            />
            <PartRow name={s.database} state={databaseState} />
          </Stack>
        </Card>

        <div role="status" aria-live="polite">
          {health.isSuccess && health.data.db === 'ok' && <Notice tone="good">{s.allGood}</Notice>}
          {health.isSuccess && health.data.db !== 'ok' && (
            <Notice tone="bad">{s.databaseDown}</Notice>
          )}
          {health.isError && <Notice tone="bad">{s.apiDown}</Notice>}
        </div>

        <Button
          size="lg"
          radius="xl"
          onClick={() => health.refetch()}
          loading={health.isFetching}
        >
          {s.retry}
        </Button>
      </Stack>
    </Container>
  )
}
