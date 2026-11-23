import { describe, expect, it } from 'vitest'

import { addressProblem, tidyAddress } from './addressRule'

describe("The API's address (A#17)", () => {
  it('loses the slashes at its end, so no call has a double slash', () => {
    expect(tidyAddress('https://api.example.net/')).toBe('https://api.example.net')
    expect(tidyAddress(' https://api.example.net// ')).toBe('https://api.example.net')
    expect(tidyAddress(undefined)).toBe('')
  })

  it('takes an https address', () => {
    expect(addressProblem('https://d111111abcdef8.cloudfront.net')).toBeNull()
    expect(addressProblem('https://d111111abcdef8.cloudfront.net/')).toBeNull()
  })

  it('takes the addresses this computer builds with: docker-compose and the dev server', () => {
    expect(addressProblem('http://localhost:8000')).toBeNull()
    expect(addressProblem('http://127.0.0.1:8000')).toBeNull()
    expect(addressProblem('http://[::1]:8000')).toBeNull()
  })

  it('refuses a build with no address, which would call the website itself', () => {
    expect(addressProblem(undefined)).toMatch(/VITE_API_URL is not set/)
    expect(addressProblem('  ')).toMatch(/VITE_API_URL is not set/)
  })

  it('refuses plain http anywhere else, and an address that only looks local', () => {
    expect(addressProblem('http://d111111abcdef8.cloudfront.net')).toMatch(/https/)
    expect(addressProblem('http://localhost.example.net')).toMatch(/https/)
    expect(addressProblem('ftp://localhost')).toMatch(/https/)
  })

  it('refuses what is not an address, or has a path after it', () => {
    expect(addressProblem('api.example.net')).toMatch(/not an address/)
    expect(addressProblem('https://api.example.net/api/v1')).toMatch(/no path/)
  })
})
