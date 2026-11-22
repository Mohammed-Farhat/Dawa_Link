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
  // The frame around every page: the way past the menus, and a page that couldn't load.
  shell: {
    skip: 'Skip to content',
    reloadTitle: 'This page needs reloading',
    reloadBody: 'DawaLink was updated, or a part of this page could not load.',
    reload: 'Reload the page',
    // The browser tab's name of a page that shows no heading (B#19).
    reservationTitle: 'Your reservation',
  },
  common: {
    back: 'Back',
    close: 'Close',
    loading: 'Loading…',
    tryAgain: 'Try again',
    cancel: 'Cancel',
    save: 'Save',
    packs: (count: number) => (count === 1 ? '1 pack' : `${count} packs`),
    aboutUsd: (amount: string) => `about $${amount}`,
    save_: (amount: string) => `Save ${amount}`,
    lbp: (amount: string) => `${amount} LBP`,
    today: 'Today',
    tomorrow: 'Tomorrow',
    // The same day inside a sentence: "until tomorrow 01:30".
    tomorrowInSentence: 'tomorrow',
    todayInSentence: 'today',
    // Heard after a link that opens another tab, never seen (WCAG 3.2.5).
    opensNewTab: '(opens in a new tab)',
    // A length of time: "45 min", "2 h", "1 h 20 min".
    duration: (hours: number, minutes: number) =>
      hours === 0 ? `${minutes} min` : minutes === 0 ? `${hours} h` : `${hours} h ${minutes} min`,
  },
  // After a form's button is pressed with a mistake (components/FormProblems.tsx).
  forms: {
    check: (count: number) =>
      count === 1 ? 'Check the field marked in red above.' : `Check the ${count} fields marked in red above.`,
  },
  welcome: {
    title: 'Your medicine, for less. Today.',
    intro:
      'Pharmacies near you sell boxes that expire soon, at up to 60% off. Reserve in seconds and pay at the counter.',
    steps: ['Search or ask', 'Reserve in one tap', 'Pick up and pay'],
    safe: 'Sealed and in date. The pharmacist checks every box.',
    signUp: 'Create a free account',
    logIn: 'Log in',
    pharmacy: 'Are you a pharmacy? Join DawaLink',
    exampleProduct: 'Example · 30 tablets',
    examplePrice: '436,000 LBP',
    exampleSaving: 'Save 145,750',
    // The ticket's own word for R-… (B wording table): "order number".
    exampleTicket: 'ORDER NUMBER',
    exampleRef: 'R-7K3Q2F',
    exampleWalk: '9 min walk · open until 23:00',
    // Said once, after a client deleted their account (R-AU10).
    accountDeleted: 'Your account is deleted.',
  },
  // Where a client lives: on the sign-up form and in the profile.
  where: {
    map: 'On the map',
    area: 'By area',
    mapWhy: 'Travel times are counted from this place. We keep it rounded to about 100 m, and never send it to the assistant or to a pharmacy.',
    useMine: 'Use my location',
    refused: 'We couldn\'t read your location. Pick it on the map, or choose "By area".',
    pinPut: 'Your place is set.',
    pinMissing: 'Tap the map where you live.',
    mapLabel: 'Map: tap to put the pin where you live',
    openMap: 'Pick on the map',
    showMap: 'Show it on the map',
    problem: 'Use your location or pick your place on the map, or choose "By area" and your district.',
    saved: 'Your place is saved.',
  },
  // Beside the form of a public page, on a computer.
  authSide: {
    title: 'Your medicine, for less. Today.',
    intro: 'Pharmacies near you sell boxes that expire soon, at up to 60% off.',
  },
  signUp: {
    title: 'Create your account',
    firstName: 'First name',
    // The label says it, not a grey placeholder that disappears when typing (B#30).
    middleName: 'Middle name (optional)',
    optional: 'Optional',
    lastName: 'Last name',
    birthDate: 'Date of birth',
    email: 'Email',
    password: 'Password',
    phone: 'Phone (optional)',
    whereTitle: 'Where you live',
    whereHint: "Searches start around it when you don't share your location.",
    governorate: 'Governorate',
    district: 'District',
    town: 'Town (optional)',
    townNone: 'Whole district',
    choose: 'Choose…',
    partProblem: 'Please write this name, with letters only.',
    birthProblem: 'Please choose your date of birth: a day in the past.',
    // A client's phone is any 6 to 15 digits (routes/accounts.py, PHONE_SHAPE), not only a
    // Lebanese number like a pharmacy's (B#4).
    phoneProblem: 'Enter a phone number (6 to 15 digits), or leave it empty.',
    // There are no separate terms: what the box accepts is the notice above it.
    terms: 'I have read and accept the privacy notice above',
    // What the assistant is given is in backend/src/dawalink/agent/context.py: keep the
    // two true together (B#16).
    termsNote:
      'DawaLink shows where a medicine is available and reserves it for you. It gives no medical advice: your pharmacist or doctor does. We keep your name, date of birth, email, phone, where you live (an area, or a place on the map) and your last searches to run your account, and never share them with a pharmacy. The assistant never gets your name, email, phone, date of birth or your place on the map: it gets the name of your home area, what you write to it, your settings, and the state of your account and of your reservations, requests and "Notify me" alerts on DawaLink.',
    submit: 'Create account',
    haveAccount: 'I already have an account',
    emailProblem: 'Please write a valid email address.',
    termsProblem: 'Please accept the privacy notice to continue.',
  },
  checkEmail: {
    title: 'Check your email',
    body: (email: string) => `We sent a link to ${email}. Open it to confirm your email, then log in.`,
    local: 'Testing on this computer? The email is in the local mailbox at http://localhost:8025.',
    // The way forward if nothing arrives (docs/03 CS-4, B#33): the button is on Home.
    noEmail: 'No email after a few minutes? Check your spam folder, or log in and press "Send the link again".',
    logIn: 'Go to log in',
  },
  verify: {
    working: 'Confirming your email…',
    done: 'Your email is confirmed. Log in to continue.',
    failed: 'This link is no longer valid.',
    // True whether the email is already confirmed or not: a link works once, so a second
    // click on it lands here too.
    failedHint: 'If your email is already confirmed, just log in. If not, log in and press "Send the link again".',
    logIn: 'Log in',
  },
  login: {
    title: 'Welcome back',
    email: 'Email',
    password: 'Password',
    code: 'Code from your authenticator app',
    submit: 'Log in',
    noAccount: 'Create a free account',
    // N-52: too many failed logins from one network address, whoever's accounts they were.
    networkBlocked: 'Too many failed logins from this network. Please try again in a few minutes.',
    // [Log in] is never greyed out: a box left empty says so (B §7).
    emailMissing: 'Type your email.',
    passwordMissing: 'Type your password.',
    codeMissing: 'Type the code from your authenticator app.',
    // The admins' login: the API answers a wrong code like a wrong password, on purpose
    // (a wrong code must not confirm the password), so the sentence names all three.
    wrongWithCode: 'Wrong email, password or code.',
    // R-AU9: on the clients' and pharmacies' login only. A lost admin is made again.
    forgot: 'Forgot your password?',
  },
  // "Forgot my password" (R-AU9): the page that asks for a link, and the link's own page.
  forgot: {
    title: 'Forgot your password?',
    intro: "Type the email of your account. We'll send you a link to set a new password.",
    submit: 'Send me a link',
    // The same sentence whatever the email: nobody learns here who has an account (R-AU7).
    sent: 'If this email has an account, a link to set a new password is on its way. It works for 30 minutes.',
    // Shown to everyone: an email never confirmed gets no link, and signing up again
    // replaces that sign-up.
    neverConfirmed: 'If you never confirmed your email, sign up again.',
    signUp: 'Sign up',
    logIn: 'Go to log in',
  },
  reset: {
    title: 'Set a new password',
    password: 'New password',
    submit: 'Set my new password',
    done: 'Your password is changed. Log in with it.',
    failed: 'This link is no longer valid.',
    // True whatever the reason: used, too old, or an older link than the last one.
    failedHint: 'A link works once, for 30 minutes, and only the newest one you asked for.',
    askAgain: 'Send me a new link',
    logIn: 'Log in',
  },
  nav: {
    label: 'Main',
    home: 'Home',
    search: 'Search',
    medicines: 'Medicines',
    myMedicines: 'My medicines',
    ask: 'Ask',
    me: 'Me',
    // The top bar of a computer.
    askAssistant: 'Ask DawaLink',
    profile: 'Profile and settings',
    account: 'Your account',
  },
  home: {
    greeting: (hour: number) =>
      hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening',
    title: 'Your medicines today',
    pickUp: 'PICK UP',
    pickUpBy: (when: string) => `By ${when}`,
    showAtCounter: 'Show at the counter',
    nothingReserved: 'Nothing is waiting for you.',
    nothingReservedHint: 'What you reserve, what a pharmacy offers you and what DawaLink looks for will be here.',
    goSearch: 'Search a medicine',
    goAsk: 'Ask DawaLink',
  },
  banner: {
    unverified: 'Confirm your email to use the assistant and to reserve.',
    resend: 'Send the link again',
    // Opening the link logs this browser out too: the person logs in again after it.
    resent: 'We sent the link again. Open it to confirm your email, then log in again.',
    paused: (until: string) => `Reservations are paused until ${until} (missed pickups).`,
    night: (opens: string) =>
      `New requests and "Notify me" start again at ${opens}. Search and reserving work now.`,
    degraded: "The assistant isn't available right now. Everything else works.",
    offline: "Can't reach DawaLink. Retrying…",
  },
  chat: {
    title: 'Ask DawaLink',
    subtitle: 'Finds medicine. You confirm. No medical advice.',
    aiNotice: "You're chatting with an AI assistant, not a pharmacist.",
    newChat: 'New chat',
    chats: 'Your chats',
    chatsHint: 'Earlier chats are kept for 30 days.',
    history: 'Earlier chats',
    untitled: 'New chat',
    current: 'Current',
    earlier: 'This is an earlier chat. You can read it, not write in it.',
    backToCurrent: 'Back to the current chat',
    placeholder: 'Write in any language…',
    messageLabel: 'Message',
    send: 'Send',
    empty: 'Tell me which medicine you need. I find where it is, and you reserve.',
    emptyExamples: ['I need Panadol', 'baddi concor 5', 'بدّي أوغمنتين'],
    working: 'Working on it…',
    oneMoment: 'One moment…',
    quickReplies: 'Quick replies',
    // Above the quick replies: they only write an answer for the client, they reserve
    // nothing (B#8).
    quickRepliesIntro: 'Or answer with one tap:',
    // Who speaks, said to a screen reader before each message (B#9).
    speaker: {
      client: 'You:',
      agent: 'DawaLink assistant:',
      admin: 'DawaLink team:',
      system: 'DawaLink:',
    } as Record<string, string>,
    // The name of the list of messages, for a screen reader.
    messagesLabel: 'Messages',
    // The answer's stream dropped after the message was kept (A#12): the reply still comes.
    replyComing: 'The connection dropped, but your message was sent. The reply will appear here.',
    newChatFailed: "We couldn't start a new chat. Please try again.",
    recommended: 'Recommended for you',
    otherOptions: (count: number) => (count === 1 ? 'See 1 other option' : `See ${count} other options`),
    hideOptions: 'Hide the other options',
    prescription: 'Prescription needed: bring it to the pharmacy.',
    used: 'Done',
    reserved: 'Reserved',
    expired: 'This option expired. Ask for fresh options.',
    // In an earlier chat nothing can be asked (B#32).
    expiredEarlier: 'This option expired.',
    call: 'Call the pharmacy',
    askPharmacistFirst: 'Ask the pharmacist before you go.',
    anotherBrand: 'Another brand',
    // What a card shows of its boxes, as search shows a box (B#5).
    card: {
      atTheCounter: 'At the counter',
      price: 'Price',
      openThatDay: 'Open that day',
      expires: 'Expires',
      // A plan card's boxes expire on different days: the soonest is the one to watch.
      soonestExpiry: 'First to expire',
      travel: 'Travel',
      // A plan's boxes are for different days of use: each was checked for its own.
      lastsEach: 'Each box lasts the days you said',
    },
    tooLong: (max: number) => `A message has ${max.toLocaleString('en')} characters at most.`,
    team: 'DawaLink team',
    report: {
      open: 'Report this answer',
      title: 'What is wrong with this answer?',
      reasons: {
        wrong_medicine: 'Not the medicine I asked for',
        wrong_information: 'Wrong information',
        not_helpful: 'It did not help',
        unsafe: 'It could be unsafe',
        other: 'Something else',
      },
      comment: 'Tell us more (optional)',
      commentHint: 'Our team reads it. Do not write your name or your phone number.',
      send: 'Send the report',
      chooseReason: 'Choose a reason first.',
      cancel: 'Cancel',
      thanks: 'Reported. Thank you: our team will look at it.',
    },
    location: {
      button: (label: string | null) => label ?? 'Set your location',
      title: 'Where are you?',
      why: 'To show walking and driving times. We round your location and never send it to the assistant.',
      useMine: 'Use my location',
      pickOnMap: 'Pick on the map',
      mapHint: 'Tap the map where you are. We round the place, as with a shared location.',
      usePin: 'Use this place',
      mapLabel: 'Map: tap to put the pin where you are',
      orDistrict: 'Or choose a district',
      district: 'District',
      useDistrict: 'Use this district',
      refused: "We couldn't read your location. Choose a district instead.",
      yours: 'Your location',
      // A name may hold its district in brackets already: "Hamra (Beirut)".
      home: (area: string) => `${area}, your home area`,
      chooseDistrict: 'Choose…',
      savedPlace: 'Your saved place',
    },
    system: {
      reserved: (ref: string) => `Reserved: ${ref}`,
      reservedHint: 'Show this number at the counter.',
      // The reservation is no longer waiting: the ticket says how it ended (A#36).
      seeReservation: 'See the reservation',
      picked_up: (ref: string) => `Picked up: ${ref}`,
      not_available: (ref: string) => `Not available: the pharmacy didn't have ${ref}`,
      cancelled: (ref: string) => `Cancelled: ${ref}`,
      cancelled_by_system: (ref: string) => `Cancelled by DawaLink: ${ref}`,
      expired: (ref: string) => `Missed pickup: ${ref} wasn't picked up in time`,
      request_reopened: (ref: string) => `Request ${ref} is open again: one box was lost.`,
      request_closed: (ref: string) => `Request ${ref} is closed.`,
      offer: 'A pharmacy has it for you.',
      // A box held for the client (B#15): what, until when, and where to accept it.
      offerHeld: (product: string, until: string) =>
        `${product} is held for you until ${until}. Accept it before then.`,
      // Once it is no longer open: accepted, declined or over. True in each case.
      offerWas: (product: string) => `A pharmacy held ${product} for you.`,
      seeOffer: 'See the offer',
      offer_ended: 'That offer has ended.',
      other: 'An update on your medicines.',
    },
  },
  notifications: {
    title: 'Notifications',
    none: 'Nothing yet. What happens to your reservations and requests is listed here.',
    unread: 'New',
    count: (count: number) => `${count} new`,
    markAll: 'Mark all as read',
    more: 'Show older ones',
  },
  search: {
    title: 'Find a medicine',
    maxPrice: 'Max price (LBP)',
    // One language in the sheet: "notify me" (docs/11 §8, B#38). My medicines keeps
    // "Watching until…" and [Stop watching] (docs/03 CS-11).
    notify: {
      button: 'Notify me if it appears',
      what: "We'll tell you if it appears in the next 6 hours. If a pharmacy lists it, the first person who asked gets it held for 2 hours.",
      maxPrice: 'The most you would pay for a pack, in LBP (optional)',
      start: 'Notify me for 6 hours',
      watching: (until: string) =>
        `We'll tell you if it appears before ${until}: you get a notification and an email.`,
      already: 'You already asked to be notified about this medicine.',
      tooMany: 'You already asked to be notified about 5 medicines, the most at a time.',
    },
    // What a screen reader hears when the results change: a summary, never every row (A#13).
    summary: (count: number, typed: string) =>
      count === 0
        ? `Nothing in stock for "${typed}"`
        : count === 1
          ? `1 medicine in stock for "${typed}"`
          : `${count} medicines in stock for "${typed}"`,
    summaryClosest: (count: number, typed: string) =>
      count === 1
        ? `No exact match for "${typed}": 1 close name in stock`
        : `No exact match for "${typed}": ${count} close names in stock`,
    summaryOne: (count: number, name: string) =>
      count === 0
        ? `No pharmacy to show for ${name}`
        : count === 1
          ? `1 pharmacy has ${name}`
          : `${count} pharmacies have ${name}`,
    arabicLetters:
      'Search reads names in English letters, like Panadol. The assistant understands Arabic: ask it to find the medicine.',
    clearFilters: 'Clear the filters',
    // "4 min by car · 21 min on foot", as the assistant's cards say it: the car first; a walk
    // of more than an hour is left out.
    byCar: (time: string) => `${time} by car`,
    onFoot: (time: string) => `${time} on foot`,
    closest: (typed: string) => `No medicine is written exactly "${typed}". These are the closest names:`,
    contains: 'Found by what it contains',
    seeAll: (count: number) => `See all ${count} pharmacies`,
    nothingInStock: (typed: string) => `No pharmacy has "${typed}" in stock right now.`,
    backToResults: (typed: string) => `All results for "${typed}"`,
    filters: 'Filters',
    label: 'Medicine name',
    placeholder: 'Search a medicine in stock',
    typeMore: 'Type the first letters of a medicine to see where it is in stock, at a discount.',
    lastSearches: 'Your last searches',
    clearSearches: 'Clear',
    openNow: 'Open now',
    upTo: (amount: string) => `up to ${amount} LBP`,
    noneForChoices: 'No pharmacy matches your filters for this medicine.',
    didYouMean: 'Did you mean',
    pickUp: 'Pick up',
    forDays: 'For how many days?',
    notSure: 'Not sure',
    other: 'Other',
    otherDays: 'Days of use',
    days: (count: number) => (count === 1 ? '1 day' : `${count} days`),
    near: 'Near',
    sort: 'Sort by',
    sorts: { best: 'Best match', nearest: 'Nearest', cheapest: 'Cheapest', latest_expiry: 'Latest expiry' },
    found: (count: number) => (count === 1 ? '1 pharmacy' : `${count} pharmacies`),
    walk: (minutes: number) => `${minutes} min walk`,
    car: (minutes: number) => `${minutes} min by car`,
    about: (km: string) => `about ${km} km`,
    openUntil: (time: string) => `open until ${time}`,
    closedNow: 'closed now',
    expires: (date: string) => `expires ${date}`,
    left: (count: number, more: boolean) => (more ? `${count}+ left` : `${count} left`),
    off: (percent: number) => `${percent}% off`,
    prescription: 'Prescription needed',
    empty: (name: string) => `No discounted stock for ${name} right now.`,
    askToFind: 'Ask DawaLink to find it',
    askToFindHint: 'The assistant keeps looking for 6 hours, and can ask pharmacies for stock that is not listed yet.',
    askDraft: (name: string) => `I need ${name}`,
    more: 'Show more',
  },
  offer: {
    lastsYour: (days: number) => (days === 1 ? 'Lasts your 1 day' : `Lasts your ${days} days`),
    doesntLast: (days: number, expiry: string) =>
      days === 1
        ? `This box expires on ${expiry}, before your 1 day ends.`
        : `This box expires on ${expiry}, before your ${days} days end.`,
    makeSure: (expiry: string) => `Expires ${expiry}: make sure that's enough.`,
    hours: 'Opening hours',
    holds: (days: number) =>
      days === 1
        ? 'You can pick up today or on its next open day.'
        : `You can pick up today or within its next ${days} open days.`,
    sealed: 'Sealed and in date. The pharmacist checks every box.',
    reserve: 'Reserve',
    gone: 'This offer is no longer available.',
    backToSearch: 'Back to the search',
  },
  reserve: {
    title: 'Reserve',
    howMany: 'How many packs?',
    fewer: 'One pack fewer',
    more: 'One pack more',
    // Why [+] stopped: the limit per medicine, or what this pharmacy has.
    mostPacks: 'You can hold 3 packs of the same medicine at a time, counting what you already reserved.',
    onlyLeft: (count: number) => (count === 1 ? 'This pharmacy has 1 pack left.' : `This pharmacy has ${count} packs left.`),
    pickUpDay: 'When will you pick it up?',
    pickUpBy: (day: string) =>
      `Pick up by ${day}: after that, the box won't last your days of use.`,
    payThere: 'You pay at the pharmacy. Reserved at once.',
    total: 'At the counter',
    submit: (count: number) => (count === 1 ? 'Reserve 1 pack' : `Reserve ${count} packs`),
    noDay: "This box can't be picked up in time to last your days of use.",
    // The sheet's own words for two refusals (A#40, B#14). The chat's cards keep the
    // general ones of `errors`.
    priceChanged: (price: string) => `The price changed to ${price}. Reserve at the new price?`,
    tooManyPacks:
      'You can hold 3 packs of the same medicine at a time, counting what you already reserved. Choose fewer packs, or pick up your reservation first.',
    otherPharmacies: 'See the other pharmacies',
  },
  request: {
    title: (ref: string) => `Request ${ref}`,
    searchingUntil: (when: string) => `DawaLink keeps looking until ${when}`,
    timeLeft: (hours: number, minutes: number) =>
      hours > 0 ? `${hours} h ${minutes} min left` : `${minutes} min left`,
    reserved: (secured: number, wanted: number) => `${secured} of ${wanted} reserved`,
    medicines: 'Medicines',
    packs: (count: number) => (count === 1 ? '1 pack' : `${count} packs`),
    steps: ['Searching', 'Found', 'Reserved'],
    asked: (count: number) =>
      count === 1 ? 'Asked 1 pharmacy for stock that is not listed yet' : `Asked ${count} pharmacies for stock that is not listed yet`,
    // "Watching" is the word of [Notify me] (docs/03 CS-11): an item of a request waits.
    watching: 'Waiting for new stock',
    // It may have ended since: the reservation, not a ticket to show (A#36).
    showTicket: (ref: string) => `Reservation ${ref}`,
    cancel: 'Cancel this request',
    // The thing is a "request" everywhere (B wording table); searching is what it does.
    cancelTitle: 'Cancel this request?',
    cancelBody: 'DawaLink stops searching. What is already reserved stays reserved.',
    cancelConfirm: 'Yes, cancel the request',
    keep: 'Keep looking',
    closed: {
      FULFILLED: 'Everything is reserved.',
      PARTIAL: 'This request has ended: part of it was found.',
      UNFULFILLED: 'This request has ended: nothing was found in time.',
      CANCELLED: 'You cancelled this request.',
    } as Record<string, string>,
    notFound: "We couldn't find this request.",
    homeLine: (ref: string, secured: number, wanted: number) =>
      `Request ${ref} · ${secured} of ${wanted} reserved`,
    open: 'See the request',
    thread: 'What DawaLink is doing',
    // An item with an offer waiting for the client's tap (amber, B#17).
    offerWaiting: 'An offer is waiting for you: see it below',
  },
  offers: {
    title: 'An offer for you',
    validUntil: (when: string) => `Held for you until ${when}`,
    released: 'A pharmacy released it for you',
    noSaving: 'No discount: the pharmacy offers it at the public price.',
    matched: 'It has just been listed',
    pickUpDay: 'When will you pick it up?',
    accept: 'Accept and reserve',
    decline: 'No thanks',
    noDay: "This box can't be picked up in time to last your days of use.",
    expires: 'Expires',
  },
  ticket: {
    header: 'Show this at the counter',
    reserved: 'Reserved',
    orderNumber: 'ORDER NUMBER',
    pickUpBy: 'Pick up by',
    pay: 'Pay at the counter',
    youSave: 'You save',
    pharmacy: 'Pharmacy',
    prescription: 'Bring your prescription',
    directions: 'Directions',
    call: 'Call',
    cancel: 'Cancel this reservation',
    contest: 'I picked it up',
    contestHint: 'Did you collect it? The pharmacy may have forgotten to mark it.',
    contested: 'Thank you. A person from DawaLink will check with the pharmacy.',
    cancelTitle: 'Cancel this reservation?',
    cancelBody: 'The box goes back on the shelf. Cancelling is free.',
    cancelConfirm: 'Yes, cancel it',
    keep: 'Keep it',
    notFound: "We couldn't find this reservation.",
    expiresOn: (date: string) => `Box expires ${date}`,
    // A reservation that is no longer waiting: its ticket names what happened (A#36).
    ended: {
      PICKED_UP: 'Picked up',
      NOT_AVAILABLE: 'Not available',
      EXPIRED_NO_SHOW: 'Missed pickup',
      CANCELLED_BY_CLIENT: 'Cancelled',
      CANCELLED_BY_SYSTEM: 'Cancelled',
    } as Record<string, string>,
    total: 'Total',
    // "Expired" is a box's date only (B#13): a reservation nobody came for is a missed pickup.
    missedPickup: "Missed pickup: it wasn't picked up in time",
  },
  medicines: {
    title: 'My medicines',
    active: 'Active',
    history: 'History',
    // The words of Home's ticket for the same link (B wording table).
    showTicket: 'Show at the counter',
    details: 'See the details',
    nothingActive: 'Nothing reserved right now.',
    nothingBefore: 'Nothing here yet.',
    watchingTitle: 'Watching',
    watchOffer: 'A pharmacy has it',
    watchUntil: (until: string, district: string | null) =>
      district ? `Watching until ${until}, around ${district}` : `Watching until ${until}`,
    watchMax: (price: string) => `up to ${price}`,
    seeOffer: 'See the offer',
    stopWatching: 'Stop watching',
    // The same buttons, told apart by a screen reader.
    stopWatchingFor: (name: string) => `Stop watching ${name}`,
    showTicketFor: (ref: string) => `Show at the counter (${ref})`,
  },
  me: {
    title: 'Profile and settings',
    missedPickups: (missed: number, limit: number) => `Missed pickups: ${missed} of ${limit}`,
    missedTitle: 'Missed pickups',
    missedRule: (limit: number, windowDays: number, pauseDays: number) =>
      `A reservation you don't pick up by the pharmacy's closing time on its day is a missed pickup: the box went back on the shelf for nobody. After ${limit} in ${windowDays} days, reserving is paused for ${pauseDays} days. Cancelling before the deadline never counts.`,
    missedNone: (windowDays: number) => `None in the last ${windowDays} days.`,
    missedContest: 'Was one counted by mistake? Open it under My medicines, History, and press "I picked it up".',
    account: 'Your account',
    logOut: 'Log out',
    profile: 'Your details',
    homeTitle: 'Where you live',
    savedPlace: 'A place on the map',
    placeTitle: 'Your place on the map',
    assistant: 'The assistant',
    phone: 'Phone (optional)',
    phoneHint: 'Only DawaLink\'s team can see it, for support. Pharmacies never do.',
    otherBrands: 'Tell me about other brands of the same medicine',
    otherBrandsHint: 'The assistant then shows them with "ask the pharmacist first". It never reserves one for you.',
    save: 'Save',
    saved: 'Saved.',
    // R-AU10. What happens is said before the password is asked; the lines are true to
    // backend/src/dawalink/services/account_deletion.py and daily.empty_deleted_account.
    deleteTitle: 'Delete my account',
    deleteOpen: 'Delete my account…',
    deleteWhat: 'If you delete your account:',
    deleteLines: [
      'Your reservations are cancelled, and your requests and "Notify me" alerts end.',
      'Your name, email, phone, date of birth, saved place and last searches are erased now.',
      'Your chats and notifications are erased within a few minutes.',
      'Past reservations stay in the pharmacies\' records, without your name.',
      'You are logged out on every device.',
    ],
    deleteFinal: 'This can\'t be undone.',
    deletePassword: 'Your password',
    deletePasswordHint: 'Type it to confirm it is you.',
    deletePasswordMissing: 'Type your password.',
    deleteWrong: 'The password is wrong.',
    deleteSubmit: 'Delete my account',
    deleteKeep: 'Keep my account',
  },
  pharmacy: {
    nav: 'Pharmacy',
    today: 'Today',
    reservations: 'Reservations',
    logOut: 'Log out',
    open: (until: string) => `open until ${until}`,
    closed: 'closed now',
    status: {
      APPROVED: 'Approved',
      PENDING: 'Waiting for approval',
      REJECTED: 'Not approved',
      SUSPENDED: 'Suspended',
    } as Record<string, string>,
    pending:
      'Your registration is being checked. You will get an email when it is approved; then you can add your stock here.',
    rejected: (reason: string | null) =>
      reason ? `Your registration was not approved: ${reason}` : 'Your registration was not approved.',
    suspended:
      'Your pharmacy is suspended: your listings are hidden. You can still hand over the reservations you hold.',
    stale: 'Your stock has not been updated for a week. Clients may see boxes you no longer have.',
    counter: 'At the counter',
    counterHint: 'Type the number the client shows you.',
    orderNumber: 'Order number',
    find: 'Find',
    noSuchNumber: (typed: string) => `No reservation here has the number ${typed}.`,
    reservation: (ref: string) => `Reservation ${ref}`,
    batchLine: (batch: string, expiry: string, each: string, total: string) =>
      `Batch ${batch} · expires ${expiry} · ${each} each · total ${total}`,
    checkPrescription: 'Check the prescription',
    pickedUp: 'Picked up',
    notAvailable: 'Not available',
    notAvailableTitle: 'Which packs are not available?',
    notAvailableBody:
      'The packs are taken out of your stock. The client is told at once, and nobody is penalised.',
    allPacks: (count: number) => (count === 1 ? 'The pack' : `All ${count} packs`),
    somePacks: (count: number) => (count === 1 ? 'Only 1 pack' : `Only ${count} packs`),
    confirmNotAvailable: 'Mark as not available',
    notAvailableTitleOne: 'Is the pack not available?',
    pickedUpDone: (ref: string) => `${ref} is handed over.`,
    notAvailableDone: (ref: string) => `${ref} is marked not available. The client is told.`,
    dueToday: 'Due today',
    nothingDue: 'Nothing to hand over today.',
    comingNext: 'For the next days',
    isNew: 'NEW · put aside',
    by: (when: string) => `by ${when}`,
    prescriptionShort: 'prescription',
    active: 'To hand over',
    history: 'Before',
    nothingActive: 'No reservation is waiting.',
    nothingBefore: 'Nothing here yet.',
    numbers: 'Today in numbers',
    newReservations: 'New reservations',
    unitsReserved: 'Packs reserved',
    liveListings: 'Packs listed',
    ask: {
      needed: (left: string) => `YOUR ANSWER IS NEEDED · ${left} LEFT`,
      title: (qty: number, product: string) => `A client nearby needs ${qty} × ${product} today`,
      youHold: (qty: number, batch: string, expiry: string) =>
        `You hold ${qty} that are not listed yet · batch ${batch} · expires ${expiry}`,
      release: 'Release',
      packs: (count: number) => (count === 1 ? '1 pack' : `${count} packs`),
      price: 'Price each (LBP)',
      suggested: (price: string, percent: number, publicPrice: string) =>
        `Suggested ${price} (${percent}% off) · public price ${publicPrice}. The price is yours to set.`,
      accept: 'Accept and offer it',
      decline: 'Decline',
      declineTitle: 'Why not?',
      declineBody: 'No penalty. You will not be asked about this medicine for a week.',
      reasons: {
        keeping_it: 'I am keeping it for my customers',
        no_longer_in_stock: 'I no longer have it',
        price: 'The price is too low',
        other: 'Another reason',
      } as Record<string, string>,
      confirmDecline: 'Decline this ask',
      declined: 'Declined. You will not be asked about this medicine for a week.',
      range: (most: string) => `Enter a price between 0 and ${most} LBP.`,
      free: 'It is free: I give it away (a donation).',
      offer: (packs: number, price: string, percent: number) =>
        percent > 0
          ? `You offer ${packs === 1 ? '1 pack' : `${packs} packs`} at ${price} each (${percent}% off).`
          : `You offer ${packs === 1 ? '1 pack' : `${packs} packs`} at ${price} each, the public price.`,
      offerFree: (packs: number) => `You offer ${packs === 1 ? '1 pack' : `${packs} packs`} for free.`,
      none: 'No pharmacy ask is waiting for you.',
      timeLeft: (hours: number, minutes: number) =>
        hours > 0 ? `${hours} H ${minutes} MIN` : `${minutes} MIN`,
    },
    notConfirmed: 'Email not confirmed',
    inventory: 'Inventory',
    listings: 'Listings',
    settings: 'Settings',
    confirmEmail:
      'Confirm your email first: open the link we sent you, then log in again. Your registration reaches our team once your email is confirmed.',
    infoRequested: (asked: string | null) =>
      asked
        ? `Our team needs something more: ${asked} Correct your details below, then save.`
        : 'Our team asked for a correction. Check your details below, then save.',
    register: {
      title: 'Join DawaLink as a pharmacy',
      intro:
        'List the boxes that expire soon, at a discount. Clients reserve them and pay at your counter.',
      approvalNote:
        'After you confirm your email, our team checks your licence and your pin. You get an email when your pharmacy is approved; then you can list your boxes.',
      account: 'Your account',
      email: 'Email',
      emailProblem: 'Enter a valid email address.',
      password: 'Password',
      termsNote:
        'Sealed, in-date packs only. Never above the public price. Keep your quantities up to date, and check your reservations every day.',
      terms: 'I agree to these terms',
      termsProblem: 'Please accept the terms to continue.',
      submit: 'Register my pharmacy',
      haveAccount: 'I already have an account',
    },
    details: {
      section: 'Your pharmacy',
      name: 'Pharmacy name',
      nameHint: 'As on your sign. Clients see it.',
      license: 'Licence number',
      phone: 'Phone',
      phoneHint: 'A Lebanese number, for example 01 234 567. Clients may call it.',
      address: 'Address',
      district: 'District',
      pin: 'Where is your pharmacy?',
      pinHint:
        'Tap the map to put the pin on your pharmacy. You can drag it. Our team checks it against your address.',
      pinSet: 'The pin is set.',
      pinHere: 'Put the pin at the centre of the map',
      map: 'Map: tap to put the pin on your pharmacy',
      mapLoading: 'Loading the map…',
      mapCredit: '© OpenStreetMap contributors',
      pickupDays: 'How long do you keep a reservation?',
      pickupDaysHint: 'A client chooses a pickup day within this time. Not picked up: back to your stock.',
      days: (count: number) => (count === 1 ? '1 day' : `${count} days`),
      hours: 'Opening hours',
      save: 'Save',
      saved: 'Saved.',
      resubmit: 'Save and send again',
      fixedTitle: 'Checked by our team',
      fixed:
        'Your name and your licence were checked when you were approved. Only our team changes them: write to us if one is wrong.',
      problems: {
        name: 'Enter the name on your sign (2 to 60 letters and digits).',
        license_number: 'Enter your licence number (letters and digits).',
        phone: 'Enter a Lebanese phone number, for example 01 234 567 or 70 123 456.',
        address: 'Enter your street and building.',
        district_id: 'Choose your district.',
        location: 'Put the pin on your pharmacy, on the map.',
        hours: 'Check your opening hours.',
        pickup_days: 'Choose 1, 2 or 3 days.',
      } as Record<string, string>,
    },
    hours: {
      days: ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'],
      open: (day: string) => `Open on ${day}`,
      closed: 'Closed',
      opens: (day: string, second: boolean) =>
        second ? `${day}: opens again at` : `${day}: opens at`,
      closes: (day: string, second: boolean) =>
        second ? `${day}: closes again at` : `${day}: closes at`,
      to: 'to',
      addRange: (day: string) => `Add a second range on ${day}`,
      removeRange: (day: string) => `Remove the second range on ${day}`,
      addShort: '+ reopens later',
      // The button's spoken name starts with its visible words (WCAG 2.5.3).
      addNamed: (day: string) => `+ reopens later (${day})`,
      removeShort: 'Remove',
      order: 'Each range opens before it closes, and the second one starts after the first ends.',
      none: 'Open at least one day a week.',
      midnight: 'For a pharmacy open until midnight, close at 00:00.',
    },
    stock: {
      title: 'Your stock',
      table: 'Your boxes, one per row',
      private:
        'Private: only you see this list. Which boxes clients see follows your rule in Settings, never earlier than 6 months before their expiry.',
      search: 'Find a medicine or a batch',
      zones: {
        ALL: 'All',
        NEAR_EXPIRY: 'Within 6 months',
        EARLY_RELEASE: 'May be asked for',
        PRIVATE: 'Private',
        EXPIRED: 'Expired',
      } as Record<string, string>,
      zoneOf: {
        NEAR_EXPIRY: 'Listed',
        EARLY_RELEASE: 'May be asked for',
        PRIVATE: 'Private',
        EXPIRED: 'Expired',
        NOT_ELIGIBLE: 'Not listed on DawaLink',
      } as Record<string, string>,
      paused: 'Paused',
      heldBack: 'Not listed yet',
      listedByYou: 'Listed by you',
      outOfStock: 'None left',
      product: 'Medicine',
      batch: 'Batch',
      expiry: 'Expires',
      daysLeft: (days: number) =>
        days < 0 ? 'expired' : days === 0 ? 'today' : days === 1 ? '1 day left' : `${days} days left`,
      inStock: 'In stock',
      reserved: 'Reserved',
      zone: 'Status',
      quantityOf: (product: string, batch: string) => `Packs of ${product}, batch ${batch}`,
      saveQuantity: 'Save',
      reservedKept: (kept: number) =>
        `${kept} reserved for clients were kept. To give one up, press Not available on its reservation.`,
      none: 'No box here yet. Upload your stock file, or add a box above.',
      noneFound: 'Nothing matches.',
      more: 'Show more',
      add: {
        title: 'Add one box',
        product: 'Medicine',
        productHint: 'Type the name, then choose it.',
        code: (code: number) => `code ${code}`,
        choose: (name: string) => `Choose ${name}`,
        change: 'Change',
        noneFound: 'No medicine with this name.',
        batch: 'Batch',
        expiry: 'Expiry date',
        expiryMonth: 'Expiry month',
        expiryYear: 'Expiry year',
        expiryHint: 'As printed on the box: the month and the year. The box counts until the last day of that month.',
        months: [
          'January',
          'February',
          'March',
          'April',
          'May',
          'June',
          'July',
          'August',
          'September',
          'October',
          'November',
          'December',
        ],
        quantity: 'How many packs',
        submit: 'Add to my stock',
        added: 'Added.',
        addedVisible: (name: string, batch: string) => `Added ${name}, batch ${batch}: clients see it now.`,
        addedHeld: (name: string, batch: string, rule: number) =>
          rule === 0
            ? `Added ${name}, batch ${batch}. Not listed yet: you list it yourself, in Listings.`
            : `Added ${name}, batch ${batch}. Not listed yet: your rule lists it when it has ${rule} days left.`,
        addedPrivate: (name: string, batch: string) =>
          `Added ${name}, batch ${batch}. Private: clients don't see it while it is more than 6 months from its expiry.`,
        addedNotListed: (name: string, batch: string) =>
          `Added ${name}, batch ${batch}. This medicine is not listed on DawaLink.`,
        problem: 'Choose a medicine, then enter its batch, its expiry date and how many packs.',
        problems: {
          product: 'Choose the medicine from the list.',
          batch: 'Enter the batch, as printed on the box.',
          expiry: 'Choose the month and the year of the expiry.',
          expired: 'This month has passed: the box has expired.',
          quantity: 'Enter how many packs (1 or more).',
          // The API's own rule (domain/pharmacy_details.py, clean_batch).
          batchRule: (most: number) =>
            `A batch is up to ${most} letters and digits, starting with one. Spaces and . / _ - are allowed.`,
        },
      },
    },
    upload: {
      title: 'Update from a file',
      steps: [
        'Download the template and open it in Excel.',
        'One row per batch: the medicine, its batch, its expiry and how many packs you have.',
        'In Excel: File, Save As, and choose CSV. Then choose that file here.',
      ],
      expiryHint:
        'Write the expiry as on the box, the month and the year: 03/2027 or 2027-03. Excel rewrites a full date in its own way.',
      replaceHint:
        'The file is your whole stock: a box that is not in it is set to 0. Reserved packs are always kept.',
      codeHint:
        'Leave the code column empty, unless a row comes back with "several medicines have this name": it then lists the code of each pack, and you write yours. A box of such a medicine is only changed by a row with its code, or by hand.',
      template: 'Download the template',
      choose: 'Choose a CSV file',
      reading: 'Reading the file…',
      waiting: (name: string) => `${name} was read. Nothing has changed yet.`,
      rows: (total: number, ok: number, errors: number) =>
        `Rows: ${total} · OK: ${ok} · With a problem: ${errors}`,
      changes: (summary: { new: number; changed: number; zeroed: number }) =>
        `${summary.new} new · ${summary.changed} changed · ${summary.zeroed} set to 0`,
      reservedKept: (count: number) =>
        count === 1
          ? '1 box has packs reserved for clients: they are kept, whatever the file says.'
          : `${count} boxes have packs reserved for clients: they are kept, whatever the file says.`,
      leftAlone: (count: number) =>
        count === 1
          ? '1 box in stock is not in this file and stays as it is: its medicine needs a code. To empty it, write its row with its code and quantity 0, or edit it below.'
          : `${count} boxes in stock are not in this file and stay as they are: their medicines need a code. To empty one, write its row with its code and quantity 0, or edit it below.`,
      problems: 'Rows that were not read',
      row: (row: number) => `Row ${row}`,
      didYouMean: (names: string) => `In our list: ${names}`,
      moreProblems: (count: number) => `and ${count} more, in the errors file.`,
      errorsFile: 'Download the rows with a problem',
      tilesLabel: 'What this file does',
      tiles: { ready: 'Ready', fix: 'Need fixing', new: 'New', zeroed: 'Set to 0' },
      changedLine: (count: number) =>
        count === 1 ? '1 box changes its quantity.' : `${count} boxes change their quantity.`,
      zeroedWarning:
        'Rows that were not read count as missing: their boxes are set to 0 too. Fix them first, or discard.',
      applyRows: (count: number) => (count === 1 ? 'Apply 1 row' : `Apply ${count} rows`),
      apply: 'Apply to my stock',
      discard: 'Discard',
      applied: 'Your stock is updated.',
      failed: (reason: string) => `This file can't be used: ${reason}.`,
    },
    listing: {
      title: 'Your boxes near their expiry',
      intro:
        'Your boxes within 6 months of their expiry. You decide which of them clients see. The price follows the days left, unless you set your own.',
      rule: (days: number) =>
        days === 0
          ? 'Your rule: you list each box yourself.'
          : `Your rule: a box is listed by itself when it has ${days} days left or fewer.`,
      changeRule: 'Change it in Settings',
      heldBack: 'Not listed yet',
      listedByYou: 'Listed by you',
      waitsFor: (days: number) =>
        days === 0
          ? 'Clients don\'t see it until you list it.'
          : `Clients will see it when it has ${days} days left, or now if you list it.`,
      listNow: 'List now',
      backToRule: 'Back to my rule',
      tiers: 'DawaLink prices',
      tier: (from: number, to: number, percent: number) =>
        `${from} to ${to} days left: ${percent}% off`,
      none: 'Nothing here yet. A box appears here when it is within 6 months of its expiry.',
      line: (batch: string, expiry: string, days: string) => `Batch ${batch} · expires ${expiry} · ${days}`,
      available: (available: number, reserved: number) =>
        `${available} available · ${reserved} reserved`,
      visible: 'Listed',
      paused: 'Paused',
      outOfStock: 'None left',
      price: (price: string, percent: number) => `${price} · ${percent}% off`,
      ownPrice: 'your price',
      systemPrice: 'DawaLink price',
      publicPrice: (price: string) => `public price ${price}`,
      setPrice: 'Set my price',
      priceOf: (product: string) => `Your price for ${product}, in LBP`,
      priceHint: 'From 0 (a donation) up to the public price.',
      priceLabel: 'Your price (LBP)',
      priceRange: (most: string) => `Enter a price between 0 and ${most} LBP.`,
      priceLive: (percent: number, publicPrice: string) => `${percent}% off · public price ${publicPrice}`,
      priceFree: (publicPrice: string) => `Free, a donation · public price ${publicPrice}`,
      savePrice: 'Save',
      cancel: 'Cancel',
      backToSystem: 'Back to the DawaLink price',
      pause: 'Pause',
      resume: 'Resume',
    },
    settingsPage: {
      title: 'Settings',
      ruleTitle: 'When your boxes are listed',
      ruleNote:
        'You decide when clients can see a box. A box is never listed with more than 180 days left.',
      ruleLabel: 'List my boxes by themselves',
      ruleChoice: (days: number) =>
        days === 0
          ? 'Never: I list each box myself'
          : `When they have ${days} days left or fewer`,
      ruleHint:
        'A box that is not listed stays private. When a client needs that medicine, DawaLink may ask you for one box: you say yes or no, and you set its price.',
      ruleSave: 'Save this rule',
      ruleSaved: 'Saved. Your listings follow it now.',
      hoursTitle: 'Opening hours, pickup time and phone',
      placeTitle: 'Your address and your place on the map',
      placeNote:
        'If your pharmacy moves, change them here. Clients see the new address at once, and our team then looks at the new pin.',
      placeSave: 'Save the new address',
      placeSaved: 'Saved. Clients now see the new address.',
      hoursNote: 'Reservations already made keep the time their client was given.',
      detailsTitle: 'Your details',
      licenseLine: (license: string) => `Licence ${license}`,
      passwordTitle: 'Password',
    },
  },
  password: {
    current: 'Current password',
    new: 'New password',
    hint: 'Your other devices are logged out.',
    rulesLabel: 'A password needs',
    rules: {
      length: 'At least 10 characters',
      capital: 'A capital letter (A to Z)',
      small: 'A small letter (a to z)',
      number: 'A number',
      symbol: 'A symbol, like ! ? @ # -',
    },
    common: 'This password is too common. Choose another.',
    met: '(met)',
    missing: '(missing)',
    submit: 'Change my password',
    done: 'Your password is changed.',
    wrong: 'The current password is wrong.',
    currentMissing: 'Type your current password.',
  },
  admin: {
    brand: 'DawaLink admin',
    nav: 'Admin console',
    loginTitle: 'Admin log in',
    logOut: 'Log out',
    back: 'Back to the list',
    more: 'Show more',
    reason: 'Reason',
    reasonHint: 'A few words, kept in the audit log. No names or phone numbers.',
    // The question a button opens when what it does needs a reason.
    why: (action: string) => `${action}: why?`,
    cancel: 'Cancel',
    changed: 'This changed since you opened it. The page now shows it as it is.',
    // A list whose request failed: said, with [Try again], never a blank page.
    listFailed: "We couldn't load this list.",
    when: (moment: string) => moment,
    tabs: {
      pharmacies: 'Pharmacies',
      escalations: 'Escalations',
      reports: 'Reported answers',
      clients: 'Clients',
      health: 'Health',
      catalog: 'Catalog',
      audit: 'Audit log',
      clock: 'Demo clock',
    },
    count: (label: string, count: number) => (count > 0 ? `${label} (${count})` : label),
    pharmacies: {
      title: 'Pharmacies',
      statuses: {
        PENDING: 'Waiting',
        APPROVED: 'Approved',
        REJECTED: 'Rejected',
        SUSPENDED: 'Suspended',
      },
      search: 'Name or licence number',
      noneWaiting: 'No registration is waiting.',
      none: 'No pharmacy here.',
      waitingSince: (when: string) => `Waiting since ${when}`,
      registered: (when: string) => `Registered ${when}`,
      infoAsked: 'More information asked',
      pinToCheck: 'Pin to check',
      movedWaiting: (count: number) =>
        count === 1
          ? '1 approved pharmacy changed its address or its pin: the pin waits for a look.'
          : `${count} approved pharmacies changed their address or their pin: the pins wait for a look.`,
      showMoved: 'Show them',
      license: (license: string) => `Licence ${license}`,
    },
    pharmacy: {
      details: 'What the pharmacy typed',
      email: 'Login email',
      pickup: 'Pickup time',
      hours: 'Opening hours',
      closed: 'closed',
      phoneChanged: (when: string) => `changed by the pharmacy on ${when}`,
      activity: 'How it is doing',
      liveListings: 'Boxes clients can see now',
      lastStockUpdate: 'Last change to its stock',
      never: 'never',
      notAvailable: 'Marked not available',
      notAvailableOf: (not: number, ended: number) =>
        ended === 0
          ? 'no reservation ended at its counter in the last 30 days'
          : `${not} of ${ended} reservations in the last 30 days (${Math.round((100 * not) / ended)}%)`,
      where: 'Where it is',
      whereHint:
        'Check that the pin is on the address. Drag it to correct it, then save the change below with a reason.',
      pinMoved: 'You moved the pin. Save it below with a reason.',
      checks: 'Checks',
      emailConfirmed: 'Its email address is confirmed.',
      licenseUnique: 'No other pharmacy has this licence number or this phone number.',
      sameAddress: 'Registered at the same address:',
      noSameAddress: 'No other pharmacy is registered at this address.',
      pinChecked: 'An admin has checked the pin.',
      pinNotChecked: 'Nobody has checked the pin yet: approving says that you did.',
      moved: (when: string) => `changed by the pharmacy on ${when}`,
      pinMovedByPharmacy: (when: string) =>
        `The pharmacy changed its address or its pin on ${when}. Look at the map: is the pin on the address?`,
      pinIsRight: 'The pin is right',
      pinConfirmed: 'Noted: the pin is checked.',
      nameCheck:
        'The assistant shows this name to clients: it must be the real name on the sign.',
      decide: 'Decide',
      approve: 'Approve',
      approved: 'Approved. The pharmacy was told, and can now add its stock.',
      reject: 'Reject',
      rejectReason: 'Why it is rejected (the pharmacy reads this)',
      confirmReject: 'Reject the registration',
      rejected: 'Rejected. The pharmacy was told why.',
      askMore: 'Ask for more information',
      askReason: 'What is missing (the pharmacy reads this)',
      confirmAsk: 'Send the question',
      asked: 'Sent. The registration stays in the queue.',
      cancel: 'Cancel',
      reasonGiven: (reason: string) => `Told to the pharmacy: ${reason}`,
      edit: 'Correct its details',
      editHint:
        'Only what you change is saved. After approval a pharmacy changes its hours, its pickup time, its phone, its address and its pin itself; its name and its licence are changed only here.',
      save: 'Save the changes',
      saved: 'Saved.',
      nothingChanged: 'Nothing was changed.',
      suspend: 'Suspend this pharmacy',
      suspendHint:
        'Its medicines stop showing to clients at once, and the offers on its boxes are cancelled. What clients already reserved there is kept: the pharmacy can still hand it over.',
      suspensionReason: 'Why (the pharmacy reads this)',
      confirmSuspend: 'Suspend',
      suspended: 'Suspended. The pharmacy was told why.',
      reinstate: 'Reinstate this pharmacy',
      reinstateHint: 'Its medicines show to clients again.',
      confirmReinstate: 'Reinstate',
      reinstated: 'Reinstated. The pharmacy was told.',
    },
    clients: {
      title: 'Clients',
      intro:
        "Each client by an ID, with what they have going. A name, an email or a phone is shown only when you ask for it on the client's page, and each look is written to the audit log.",
      all: 'All',
      statuses: {
        UNVERIFIED: 'Email not confirmed',
        ACTIVE: 'Active',
        PAUSED: 'Paused',
        SUSPENDED: 'Suspended',
        DELETED: 'Deleted',
      },
      // The names of the list's two rows of choices.
      account: 'Account',
      show: 'Show',
      having: {
        all: 'Everyone',
        reservation: 'With a reservation',
        picked_up: 'Picked up an order',
        request: 'With an open request',
        look: 'Needs a look',
      },
      ref: 'Order or request number',
      refHint: 'For example R-7K3Q2F: it finds the client it belongs to.',
      none: 'No client matches.',
      // Followed by the client's short ID: "Client 3f9a12bc".
      one: 'Client',
      noDistrict: 'No district',
      orders: (count: number) => (count === 1 ? '1 open reservation' : `${count} open reservations`),
      pickedUp: (count: number) => `${count} picked up`,
      requests: (count: number) => (count === 1 ? '1 open request' : `${count} open requests`),
      noShows: (count: number) =>
        count === 1 ? '1 missed pickup in 30 days' : `${count} missed pickups in 30 days`,
      contestWaiting: 'Says they picked it up',
      flagged: 'Flagged',
      pausedUntil: (when: string) => `Reservations paused until ${when}`,
      reservations: 'Reservations',
      reservationsHint: 'The last 30, newest first.',
      noReservations: 'No reservation yet.',
      packs: (count: number) => (count === 1 ? '1 pack' : `${count} packs`),
      orderStates: {
        OFFERED: 'Offer waiting for the client',
        RESERVED: 'To pick up',
        PICKED_UP: 'Picked up',
        NOT_AVAILABLE: 'Not available at the pharmacy',
        EXPIRED_NO_SHOW: 'Missed pickup',
        CANCELLED_BY_CLIENT: 'Cancelled by the client',
        CANCELLED_BY_SYSTEM: 'Cancelled by DawaLink',
      },
      notCounted: 'Missed pickup, cleared',
      pickUpBy: (when: string) => `pick up by ${when}`,
      reservedOn: (when: string) => `reserved ${when}`,
      requestsTitle: 'Requests',
      requestsHint:
        'A request is "find these medicines for me": the assistant searches for 6 hours. The last 10, the open ones first.',
      noRequests: 'No request yet.',
      requestOpen: (when: string) => `Searching until ${when}`,
      outcomes: {
        FULFILLED: 'Everything reserved',
        PARTIAL: 'Part of it reserved',
        UNFULFILLED: 'Nothing found',
        CANCELLED: 'Cancelled',
      },
      requestClosed: 'Closed',
      secured: (secured: number, medicines: number) =>
        medicines === 1
          ? `${secured} of 1 medicine reserved`
          : `${secured} of ${medicines} medicines reserved`,
      startedOn: (when: string) => `started ${when}`,
      contests: 'Says they collected it',
      contestsHint:
        'The client says they collected this at the counter, but the pharmacy never pressed [Picked up], so it was counted as a missed pickup. Call the pharmacy. If the client did collect it, clear it: it stops counting against them.',
      contestedOn: (when: string) => `said so ${when}`,
      clear: 'Clear this missed pickup',
      cleared: 'Cleared: it no longer counts as a missed pickup.',
      flags: 'Flagged by the system',
      flagsHint: 'Raised by code for a person to look at. A flag holds counts, never a message.',
      actions: 'Actions',
      liftPause: 'Lift the pause',
      lifted: 'The pause is lifted.',
      suspend: 'Suspend this client',
      suspendHint:
        'They are logged out at once. Their open reservations, offers, requests and watches are cancelled, and the flags about them are closed.',
      suspended: 'Suspended. Everything they had going was cancelled.',
      reinstate: 'Reinstate this client',
      reinstated: 'Reinstated.',
      contact: 'Contact details',
      contactHint: 'For support only. Each look is written to the audit log; 30 an hour at most.',
      showContact: 'Show the name, email and phone',
      contactLimit: 'You have viewed 30 clients in an hour. This is noted in the audit log; try again later.',
      fullName: 'Name',
      email: 'Email',
      phone: 'Phone',
      noPhone: 'not given',
      // A client who deleted their account (R-AU10): there is nothing to show.
      deletedContact: 'This client deleted their account: no name, email or phone is kept.',
    },
    // A flag is shown on the page of the client it is about: there is no page of flags.
    flags: {
      rules: {
        guardrail_repeat: 'Messages that try to give the assistant orders',
        no_show_pause: 'Paused for missed pickups',
      },
      severity: { low: 'Low', high: 'High' },
      evidence: { triggers_24h: 'attempts in 24 hours', counted_no_shows: 'missed pickups counted' },
      raised: (when: string) => `raised ${when}`,
      dismiss: 'Dismiss this flag',
      // It records that someone warned the account's owner. It sends nothing itself.
      warn: 'Note a warning',
      warnHint:
        '"Note a warning" records that you warned the client: DawaLink sends them nothing, tell them yourself. To suspend them, use "Suspend this client" under Actions: it closes this flag too.',
      done: 'Done.',
    },
    catalog: {
      title: 'Catalog',
      intro: "The Ministry's list as imported, to read. It changes only by the import script and the team's files.",
      source: (file: string, date: string, imported: number, total: number) =>
        `Last import: ${file}, list of ${date}: ${imported.toLocaleString('en')} of ${total.toLocaleString('en')} products.`,
      search: 'Name of a medicine',
      none: 'No product with this name.',
      table: 'Products',
      columns: { name: 'Medicine', code: 'Code', pack: 'Form and pack', price: 'Public price', flags: 'Rules', same: 'Same medicine' },
      controlled: 'Controlled: never shown',
      prescription: 'Prescription notice',
      // What the list is, never "no prescription needed": DawaLink never tells anyone that.
      noPrescription: "On the Ministry's no-prescription list",
      same: (others: number) => (others === 1 ? '1 other brand' : `${others} other brands`),
      alone: 'none',
    },
    health: {
      title: 'Health',
      period: 'Period',
      // What the server counts: the last 24 hours, not the day since midnight.
      days: (count: number) => (count === 1 ? 'Last 24 hours' : `${count} days`),
      none: 'no data',
      noAlerts: 'No alert right now.',
      alerts: {
        agent_error_rate: 'More than 5% of the assistant turns failed in the last 15 minutes.',
        llm_spend: "More than 80% of the month's budget for the assistant is spent.",
        dead_emails: 'More than 10 emails could not be sent in the last hour.',
        clock_check_late: 'The worker is more than 2 minutes late on deadlines.',
        agent_turn_stuck: 'An assistant turn failed 4 times and waits.',
        llm_daily_cap: "Today's share of the assistant's budget is used: the assistant is off until midnight.",
        contact_views_limit: 'An admin reached the limit of contact details in the last 24 hours. See the audit log.',
        books_do_not_add_up:
          "The daily check found reserved counts that don't match the reservations. The IDs are in the worker's log (books_do_not_add_up).",
        retention_failing:
          "The daily clean-up of old data has failed two days in a row. See the worker's log (retention_failed).",
        admin_login_locked: "An admin's login was locked after 5 wrong tries in the last 24 hours. See the audit log.",
      },
      agent: 'The assistant',
      turns: 'Turns',
      latency: 'Time per turn (half of them · 95%)',
      errors: 'Failed turns',
      fallbacks: 'Answered with a fixed text',
      guards: 'Turns where a guard fired',
      tools: 'Tool calls · tool errors',
      tokens: 'Tokens read · written',
      cost: 'Cost',
      month: 'This month / budget',
      model: 'Model',
      prompt: 'Prompt version',
      requests: 'Requests',
      closed: 'Closed',
      fulfilled: 'Fulfilled within the 6 hours',
      replans: 'Re-plans per request',
      earlyRelease: 'Pharmacies asked · accepted',
      perFulfilled: "The assistant's cost per fulfilled request",
      escalated: 'Escalated',
      marketplace: 'Reservations',
      reservations: 'Reserved',
      pickedUp: 'Picked up',
      notAvailable: 'Not available at the pharmacy',
      noShows: 'Missed pickups',
      unitsSaved: 'Packs saved from expiring',
      system: 'System',
      clockLate: 'Worker',
      secondsLate: (late: number) => (late === 0 ? 'on time' : `${late} s late`),
      turnsWaiting: 'Assistant turns waiting',
      turnsStuck: 'Turns that failed 4 times',
      emailsFailed: 'Emails not sent',
    },
    escalations: {
      title: 'Escalations',
      intro:
        'A client who needs a person: they asked the assistant for one, or they say a missed pickup was counted by mistake.',
      open: 'To answer',
      resolved: 'Closed',
      none: 'Nobody is waiting for an answer.',
      noneResolved: 'Nothing was closed yet.',
      reasons: {
        client_asked_human: 'Asked for a person',
        emergency_claim: 'Emergency claim',
        cannot_resolve: 'The assistant is stuck',
        window_ending: 'Search time ending',
        suspicious: 'Suspicious',
        complaint: 'Complaint',
      },
      states: { OPEN: 'New', IN_PROGRESS: 'Answered', RESOLVED: 'Closed' },
      request: (ref: string) => `Request ${ref}`,
      opened: (when: string) => `opened ${when}`,
      client: (short: string) => `Client ${short}`,
      openClient: "open the client's page",
      summary: 'What the client needs',
      added: 'Added later',
      // Shown on an emergency claim only: that is where the temptation is.
      noPriority:
        'Nobody can change who gets stock first, here or anywhere. For an emergency: point to a doctor or to emergency services, and help as a person.',
      missed: 'The missed pickup',
      missedHint:
        'Call the pharmacy. If the client did collect it, clear it: it stops counting against them. Nothing else changes.',
      clear: 'Clear the missed pickup',
      cleared: 'Cleared: it no longer counts against the client. Tell them, then close the case.',
      thread: 'The chat',
      threadNote:
        "The client's and the assistant's messages hold no personal details. A reply from our team is shown as it was typed.",
      noThread: 'No chat goes with this case.',
      authors: { client: 'Client', agent: 'Assistant', admin: 'DawaLink team', system: 'DawaLink' },
      card: (kind: string) => `[card: ${kind}]`,
      reply: 'Write to the client',
      replyHint:
        'The client reads it in the chat exactly as you write it, signed "DawaLink team". Give a phone number only when the situation needs one.',
      left: (count: number) => `${count} characters left`,
      send: 'Send',
      sent: 'Sent. The client was notified.',
      close: 'Close this case',
      note: 'Note (optional)',
      noteHint: 'What was done, for the team. The client does not see it.',
      closed: 'Closed.',
      resolvedNote: (note: string) => `Closed: ${note}`,
    },
    reports: {
      title: 'Reported answers',
      intro:
        'Replies of the assistant that a client marked with a thumbs-down. "Real problem" keeps the reply as a case to test the assistant against.',
      states: { NEW: 'To review', CONFIRMED: 'Real problems', DISMISSED: 'Not a problem' },
      none: 'No answer to review.',
      noneOther: 'Nothing here.',
      asked: 'The client wrote',
      answered: 'The assistant answered',
      comment: (comment: string) => `The client's comment: ${comment}`,
      // The label alone: the comment beside it keeps its own language (B#10).
      commentLabel: "The client's comment:",
      confirm: 'Real problem',
      dismiss: 'Not a problem',
      reviewed: 'Reviewed.',
    },
    audit: {
      title: 'Audit log',
      intro: 'Who changed what. Nothing here can be edited or deleted.',
      kind: 'Kind of action',
      kinds: {
        '': 'All',
        'pharmacy.': 'Pharmacies',
        'escalation.': 'Escalations',
        'answer_report.': 'Reported answers',
        'order.': 'Reservations',
        'inventory.': 'Stock',
        'clock.': 'Demo clock',
        'pii.': 'Views of personal data',
        'client.': 'Clients',
        'abuse_flag.': 'Flags',
      },
      actor: 'Who',
      actors: {
        '': 'Anyone',
        ADMIN: 'Admin',
        PHARMACY: 'Pharmacy',
        CLIENT: 'Client',
        AGENT: 'Assistant',
        SYSTEM: 'System',
      },
      entity: 'ID of the thing changed',
      columns: { when: 'When', who: 'Who', action: 'Action', what: 'On', change: 'Change', reason: 'Reason' },
      none: 'No event matches.',
      table: 'Audit events',
    },
    clock: {
      title: 'Demo clock',
      intro:
        "Moves the app's time forward to show what happens later: an offer expiring, the one-hour-left check, a missed pickup. Logins are not affected. A move can't be undone. Every move is in the audit log.",
      now: (when: string) => `The app's time: ${when}`,
      ahead: (minutes: number) =>
        minutes === 0
          ? 'Same as the real time.'
          : `${minutes === 1 ? '1 minute' : `${minutes} minutes`} ahead of the real time.`,
      steps: [
        { minutes: 30, label: '+30 min' },
        { minutes: 120, label: '+2 h' },
        { minutes: 360, label: '+6 h' },
        { minutes: 1440, label: '+1 day' },
      ],
      moved: 'The clock moved.',
      reason: 'Moved from the demo clock screen',
    },
  },
  // A limit worded from what the API says about it (strings/failure.ts): how long to wait,
  // or when requests open again (A#34, B#36, B#37).
  limits: {
    tryInMinutes: (minutes: number) =>
      minutes === 1 ? 'Please try again in about a minute.' : `Please try again in about ${minutes} minutes.`,
    today: "You have reached today's limit. Please try again tomorrow.",
    chatToday: "You have reached today's limit of messages to the assistant. Please try again tomorrow: search still works.",
    comeBack: (when: string) => `DawaLink starts new searches during the day. Please come back ${when}.`,
    comeBackAt: (at: string) => `at ${at}`,
    comeBackTomorrow: (at: string) => `tomorrow at ${at}`,
    comeBackOn: (day: string, at: string) => `on ${day} at ${at}`,
    // An account locked after wrong passwords (R-AU2), with the API's own wait: a login,
    // or Change password.
    locked: (minutes: number) =>
      minutes === 1
        ? 'Too many tries. Please try again in about a minute.'
        : `Too many tries. Please try again in about ${minutes} minutes.`,
    // Every slot that checks a password is taken for a moment (the API's 503 with a wait).
    // What the person typed stays in the form.
    busy: 'DawaLink is busy. Please try again in a moment.',
  },
  // What the website says for each error code (docs/11 §7). Never the server's sentence.
  errors: {
    UNREACHABLE: "Can't reach DawaLink. Check your connection and try again.",
    INTERNAL_ERROR: 'Something went wrong on our side. Please try again.',
    SERVICE_UNAVAILABLE: 'DawaLink is temporarily unavailable. Please try again.',
    VALIDATION_ERROR: 'Some fields are missing or invalid.',
    UNAUTHENTICATED: 'Please log in again.',
    FORBIDDEN: "This account can't do that.",
    NOT_FOUND: "We couldn't find that.",
    RATE_LIMITED: 'Too many tries. Please wait a minute.',
    WEAK_PASSWORD:
      'A password needs at least 10 characters, with a capital letter, a small letter, a number and a symbol.',
    SIGNUP_LIMIT: 'Too many sign-ups from this network. Please try again later.',
    INVALID_CREDENTIALS: 'Wrong email or password.',
    ACCOUNT_LOCKED: 'Too many failed logins. Please try again in 15 minutes.',
    ACCOUNT_SUSPENDED: 'This account is suspended.',
    TOKEN_INVALID: 'This link is no longer valid.',
    EMAIL_NOT_VERIFIED: 'Please confirm your email first.',
    CLIENT_PAUSED: 'Reservations are paused after missed pickups.',
    LISTING_NOT_AVAILABLE: 'This option is no longer available.',
    NOT_ENOUGH_STOCK: 'Someone reserved this a moment ago.',
    PRICE_CHANGED: 'The price changed. Ask for fresh options.',
    LIMIT_OPEN_ORDERS: 'You have 5 open reservations, the maximum.',
    // True whatever the client holds now: what they reserved before counts too (B#14).
    LIMIT_GROUP_UNITS: 'You can hold 3 packs of the same medicine at a time, counting what you already reserved.',
    GROUP_ITEM_FAILED: 'One medicine on this card was just taken. Nothing was reserved.',
    RESERVATION_NOT_ACTIVE: 'This reservation is no longer active.',
    DOES_NOT_FIT: 'This box expires before your days of use end.',
    PICKUP_DAY_INVALID: "The pharmacy can't hold it for that day.",
    // Said when the API gave no time: true before 08:00 as well as after 20:00 (B#37).
    // With its `opens_at`, strings/failure.ts says the day and the hour.
    OUTSIDE_REQUEST_HOURS: 'DawaLink starts new searches between 08:00 and 20:00. Please come back then.',
    LIMIT_OPEN_REQUESTS: 'You already have 2 open requests, the maximum.',
    PROPOSAL_EXPIRED: 'This option expired. Ask the assistant for fresh options.',
    PROPOSAL_USED: 'This card was already used.',
    CONVERSATION_BUSY: 'One moment…',
    ASSISTANT_UNAVAILABLE: "The assistant isn't available right now. Everything else works.",
    TOKEN_BUDGET_EXCEEDED: "You've reached today's limit for the assistant. It is back tomorrow.",
    MESSAGE_TOO_LONG: 'A message has 1,000 characters at most.',
    ORIGIN_REJECTED: 'Please open DawaLink from its own address and try again.',
    METHOD_NOT_ALLOWED: "That action isn't available here.",
    IDEMPOTENCY_KEY_REQUIRED: 'Something went wrong on our side. Please try again.',
    BODY_TOO_LARGE: 'That is too much text to send at once.',
    PHARMACY_NOT_APPROVED: "Your pharmacy can't do this in its current status.",
    // "licence", as the registration form spells it.
    LICENSE_TAKEN: 'A pharmacy with this licence number is already registered.',
    PHONE_TAKEN: 'A pharmacy with this phone number is already registered.',
    OFFER_NOT_OPEN: 'This offer is no longer open.',
    NOT_CONTESTABLE: "This reservation can't be contested any more.",
    // "Notify me", the client's word for a watch (docs/11 §8, B#38).
    LIMIT_WATCHES: 'You already asked to be notified about 5 medicines: that is the most.',
    WATCH_EXISTS: 'You already asked to be notified about this medicine.',
    PRODUCT_NOT_ALLOWED: "This medicine isn't available on DawaLink.",
    REQUEST_CLOSED: 'This request is closed.',
    CLAIM_NOT_ACTIVE: 'This need is already met or has ended.',
    LIMIT_EARLY_RELEASE: 'Pharmacies were asked about this medicine a short while ago.',
    SELECTION_INVALID: 'Choose at least one of the medicines on this card.',
    ALREADY_REPORTED: 'You already reported this answer. Thank you.',
    PICKUP_DEADLINE_PASSED: 'The pickup time has passed: this box is back in your stock.',
    UNITS_INVALID: 'That number of packs is not possible here.',
    UPLOAD_FAILED: "We couldn't read this file. Please use the template.",
    FILE_TOO_LARGE: 'This file is too large (5 MB at most).',
    UPLOAD_NOT_VALIDATED: 'This upload was discarded or replaced. Please upload the file again.',
    ITEM_EXISTS: 'This batch is already in your stock: change its quantity instead.',
    PRICE_ABOVE_PUBLIC: "The price can't be above the public price.",
    ASK_NOT_OPEN: 'This ask is no longer open.',
    REASON_REQUIRED: 'Please write the reason.',
    CHANGED_SINCE: 'This changed since you opened it. Look at it again.',
    DEMO_MODE_OFF: 'The demo clock is off.',
  } as Record<string, string>,
} as const

/** What to say for an error code. An unknown code gets the general sentence. */
export function errorMessage(code: string): string {
  return strings.errors[code] ?? strings.errors.INTERNAL_ERROR
}
