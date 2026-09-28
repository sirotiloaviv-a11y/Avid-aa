// The DRIP wordmark as one even-odd path on a 320 × 100 box.
// Keep in sync with #drip-mark in index.html.
export const MARK_PATH =
  'M0 0H40A50 50 0 0 1 40 100H0ZM22 22V78H40A28 28 0 0 0 40 22Z' +
  'M106 0H150A31 31 0 0 1 150 62H128V100H106ZM128 20V42H150A11 11 0 0 0 150 20ZM146 62H168L190 100H166Z' +
  'M206 0H228V100H206Z' +
  'M244 0H288A31 31 0 0 1 288 62H266V100H244ZM266 20V42H288A11 11 0 0 0 288 20Z';
export const MARK_W = 320;
export const MARK_H = 100;

export const COLORS = [
  { id: 'onyx', name: 'Onyx', body: '#141414', ink: '#f4f1ea' },
  { id: 'slate', name: 'Slate', body: '#3a4350', ink: '#f4f1ea' },
  { id: 'sage', name: 'Sage', body: '#6f7b67', ink: '#f4f1ea' },
  { id: 'sand', name: 'Sand', body: '#cbbea6', ink: '#141414' },
];

// Placeholder price for the demo cart. Not a real offer.
export const PRICE = 59;
export const CURRENCY = 'USD';
