// Small inline stroke icon set, so the UI has no icon-library dependency.
const PATHS = {
  shield: <path d="M12 3l8 3v6c0 4.6-3.3 8.4-8 9.8C7.3 20.4 4 16.6 4 12V6l8-3z" />,
  shieldCheck: <><path d="M12 3l8 3v6c0 4.6-3.3 8.4-8 9.8C7.3 20.4 4 16.6 4 12V6l8-3z" /><path d="M8.8 12.2l2.3 2.3 4.3-4.6" /></>,
  gauge: <><path d="M4.5 17a8.5 8.5 0 1115 0" /><path d="M12 13l4-4.5" /><circle cx="12" cy="13.5" r="1.3" /></>,
  sparkles: <><path d="M12 3.5l1.6 4.4L18 9.5l-4.4 1.6L12 15.5l-1.6-4.4L6 9.5l4.4-1.6L12 3.5z" /><path d="M18.5 15l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7.7-1.8z" /></>,
  list: <><path d="M9 6h11M9 12h11M9 18h11" /><circle cx="4.5" cy="6" r="1" /><circle cx="4.5" cy="12" r="1" /><circle cx="4.5" cy="18" r="1" /></>,
  plug: <><path d="M9 3v5M15 3v5" /><path d="M6 8h12v3a6 6 0 01-12 0V8z" /><path d="M12 17v4" /></>,
  refresh: <><path d="M20 11a8 8 0 00-14.3-4.9L4 8" /><path d="M4 4v4h4" /><path d="M4 13a8 8 0 0014.3 4.9L20 16" /><path d="M20 20v-4h-4" /></>,
  check: <path d="M5 12.5l4.2 4.2L19 7" />,
  x: <path d="M6 6l12 12M18 6L6 18" />,
  chevronDown: <path d="M6 9l6 6 6-6" />,
  chevronRight: <path d="M9 6l6 6-6 6" />,
  alert: <><path d="M12 4l9 16H3l9-16z" /><path d="M12 10v4" /><circle cx="12" cy="17" r=".6" /></>,
  wrench: <path d="M14.7 6.3a4 4 0 00-5.4 5.1L4 16.7V20h3.3l5.3-5.3a4 4 0 005.1-5.4l-2.5 2.5-2.6-.5-.5-2.6 2.6-2.4z" />,
  clock: <><circle cx="12" cy="12" r="8.5" /><path d="M12 7.5V12l3 2" /></>,
  search: <><circle cx="11" cy="11" r="6.5" /><path d="M16 16l4.5 4.5" /></>,
  bolt: <path d="M13 3L5 13.5h6L10 21l8-10.5h-6L13 3z" />,
  globe: <><circle cx="12" cy="12" r="8.5" /><path d="M3.5 12h17M12 3.5c2.5 2.7 3.5 5.5 3.5 8.5s-1 5.8-3.5 8.5c-2.5-2.7-3.5-5.5-3.5-8.5s1-5.8 3.5-8.5z" /></>,
  lock: <><rect x="5" y="10.5" width="14" height="10" rx="2" /><path d="M8 10.5V8a4 4 0 018 0v2.5" /></>,
  trendUp: <><path d="M3.5 16.5l6-6 4 4 7-7" /><path d="M15 7.5h5.5V13" /></>,
  trendDown: <><path d="M3.5 7.5l6 6 4-4 7 7" /><path d="M15 16.5h5.5V11" /></>,
  link: <><path d="M10 14a4 4 0 005.7 0l3-3a4 4 0 00-5.7-5.7l-1 1" /><path d="M14 10a4 4 0 00-5.7 0l-3 3a4 4 0 005.7 5.7l1-1" /></>,
  unlink: <><path d="M15.5 13.5l3.2-2.5a4 4 0 00-5.7-5.7L11 7" /><path d="M8.5 10.5L5.3 13a4 4 0 005.7 5.7l2-1.7" /><path d="M4 4l16 16" /></>,
  external: <><path d="M14 4h6v6" /><path d="M20 4l-9 9" /><path d="M18 14v5a1 1 0 01-1 1H5a1 1 0 01-1-1V7a1 1 0 011-1h5" /></>,
  layers: <><path d="M12 3l9 5-9 5-9-5 9-5z" /><path d="M3 13l9 5 9-5" /></>,
  menu: <path d="M4 7h16M4 12h16M4 17h16" />,
  rotate: <><path d="M4 12a8 8 0 108-8 8.5 8.5 0 00-6 2.5L4 8.5" /><path d="M4 4v4.5h4.5" /></>,
};

export function Icon({ name, className = 'h-4 w-4', strokeWidth = 1.8, ...rest }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
      {...rest}
    >
      {PATHS[name] ?? PATHS.shield}
    </svg>
  );
}

export function Spinner({ className = 'h-4 w-4' }) {
  return (
    <svg viewBox="0 0 24 24" className={`${className} animate-spin`} fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity=".2" strokeWidth="2.5" />
      <path d="M21 12a9 9 0 00-9-9" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  );
}
