import { strings } from '../../strings/en'

// What the client's account forms (sign-up, the profile) check before sending, as the API
// checks it.

/** The API's bounds on what a person types (api/schemas/accounts.py): a longer text is
 * never sent, so it is never refused for its length (A#35). */
export const MAX = { name: 40, email: 320, password: 200, phone: 30, code: 10 } as const

/** A client's phone as the API takes it (`PHONE_SHAPE` in api/routes/accounts.py): 6 to
 * 15 digits with the marks people write around them. */
const PHONE_SHAPE = /^\+?(?:[\s.()-]*\d){6,15}[\s.()-]*$/

/** What is wrong with a phone, or null: an empty one is fine, the phone is optional (B#4). */
export function phoneProblem(phone: string): string | null {
  const typed = phone.trim()
  return !typed || PHONE_SHAPE.test(typed) ? null : strings.signUp.phoneProblem
}

/** The API's fields that are "where you live" on a form. */
export const WHERE_FIELDS = ['home_place', 'location', 'district_id', 'home_area_id', 'lat', 'lon']
