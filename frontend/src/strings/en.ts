// Every word the website shows lives in this file (docs/11 §8), so the wording stays
// consistent and an Arabic interface later is a translation, not a rewrite.

export const strings = {
  appName: 'DawaLink',
  status: {
    title: 'DawaLink is being built',
    intro: 'This page shows whether the parts of the system can reach each other.',
    website: 'Website',
    api: 'API',
    database: 'Database',
    running: 'Running',
    checking: 'Checking…',
    notReachable: 'Not reachable',
    version: (version: string) => `Version ${version}`,
    allGood: 'Everything is running.',
    databaseDown: "The API is running, but it can't reach the database.",
    apiDown: "The website can't reach the API. Is it started?",
    retry: 'Check again',
  },
  notFound: {
    title: "This page doesn't exist",
    back: 'Go to the home page',
  },
} as const
