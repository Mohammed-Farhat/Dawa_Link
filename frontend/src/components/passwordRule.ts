// R-AU1, as the server checks it (services/auth.py): at least 10 characters with a
// capital letter, a small letter, a number and a symbol. A form only shows it early; the
// server's answer is the one that counts.

export const PASSWORD_PARTS = {
  length: (password: string) => password.length >= 10,
  capital: (password: string) => /[A-Z]/.test(password),
  small: (password: string) => /[a-z]/.test(password),
  number: (password: string) => /[0-9]/.test(password),
  // The plain symbols of a keyboard: ! " # $ % & ' ( ) * + , - . / : ; < = > ? @ [ \ ] ^ _ ` { | } ~
  symbol: (password: string) => /[!-/:-@[-`{-~]/.test(password),
} as const

export type PasswordPart = keyof typeof PASSWORD_PARTS

export const PASSWORD_PART_NAMES = Object.keys(PASSWORD_PARTS) as PasswordPart[]

/** What a password still lacks, by the rule's own names. Empty: it holds every part. */
export function passwordGaps(password: string): PasswordPart[] {
  return PASSWORD_PART_NAMES.filter((part) => !PASSWORD_PARTS[part](password))
}
