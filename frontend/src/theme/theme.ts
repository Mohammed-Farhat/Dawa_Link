import { createTheme, type MantineColorsTuple } from '@mantine/core'

// Design tokens from docs/11 §2 (the v2 design). A color is added here when a screen first uses it.
// The fixed points are named in the doc; the shades between them are steps along the same line.

/** Text and dark surfaces. ink.9 = "ink", ink.7 and ink.6 = secondary text and hints, ink.4 = input borders. */
const ink: MantineColorsTuple = [
  '#F4F5FA',
  '#E4E6F0',
  '#C9CCDA',
  '#AEB1C4',
  '#8A8EA6',
  '#7B7F97',
  '#6B6F87',
  '#4A4E69',
  '#2B2E47',
  '#14162B',
]

/** The one action color. blue.6 = buttons and links, blue.0 = selected and "searching" tints. */
const blue: MantineColorsTuple = [
  '#ECEFFF',
  '#D9DFFE',
  '#B4BFFA',
  '#8D9DF5',
  '#6A7EEF',
  '#4A62E6',
  '#2F4BDB',
  '#2640C2',
  '#1E35A6',
  '#172A87',
]

/** Ready, fits, picked up. green.7 = text and icons, green.0 = its tint. */
const green: MantineColorsTuple = [
  '#E2F6EB',
  '#C6ECD7',
  '#9CDDB9',
  '#6FCB98',
  '#45B87A',
  '#22A262',
  '#128E55',
  '#0B7A4B',
  '#08633D',
  '#064C2F',
]

/** Your tap is needed. amber.8 = text, amber.0 = its tint. */
const amber: MantineColorsTuple = [
  '#FFF0D9',
  '#FFE2B5',
  '#FFCE85',
  '#FBB753',
  '#F09F2B',
  '#D9860F',
  '#BC6F04',
  '#A45F01',
  '#8F4E00',
  '#6E3C00',
]

/** Failed, missed, cancel. red.7 = text and icons, red.0 = its tint. */
const red: MantineColorsTuple = [
  '#FDE9E9',
  '#FAD1D2',
  '#F4A6A8',
  '#EC787C',
  '#E25056',
  '#D5373D',
  '#CB2D34',
  '#C0262D',
  '#9E1D24',
  '#7C151B',
]

export const theme = createTheme({
  fontFamily: "'Readex Pro Variable', system-ui, sans-serif",
  headings: { fontFamily: "'Readex Pro Variable', system-ui, sans-serif", fontWeight: '600' },
  colors: { ink, blue, green, amber, red },
  primaryColor: 'blue',
  primaryShade: 6,
  black: ink[9],
  white: '#FFFFFF',
  defaultRadius: 'lg',
  radius: { xs: '8px', sm: '12px', md: '16px', lg: '20px', xl: '28px' },
  fontSizes: { xs: '13px', sm: '14px', md: '17px', lg: '18px', xl: '22px' },
})

export const pageBackground = ink[0]
