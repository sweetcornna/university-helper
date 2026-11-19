/*
 * Accessible on/off switch: a 44px touch target around a 24×44 track whose
 * 20px knob travels exactly track-inner-width − knob-width (40 − 20 = 20px).
 * The state is also written out (开/关) so it does not depend on colour.
 */
export default function Toggle({ checked, onChange, label, disabled = false, id }) {
  return (
    <button
      type="button"
      role="switch"
      id={id}
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => !disabled && onChange(!checked)}
      className="inline-flex min-h-[44px] min-w-[44px] cursor-pointer items-center justify-center gap-2 rounded-full px-1.5 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary disabled:cursor-not-allowed disabled:opacity-50"
    >
      <span
        aria-hidden="true"
        className={`relative inline-flex h-6 w-11 items-center rounded-full border px-0.5 transition-colors duration-150 ${
          checked ? 'border-primary bg-primary' : 'border-border bg-sunken'
        }`}
      >
        <span
          className={`inline-block h-5 w-5 rounded-full bg-surface shadow-sm transition-transform duration-150 ${
            checked ? 'translate-x-5' : 'translate-x-0'
          }`}
        />
      </span>
      <span aria-hidden="true" className={`w-4 text-xs font-semibold ${checked ? 'text-primary' : 'text-text-muted'}`}>
        {checked ? '开' : '关'}
      </span>
    </button>
  )
}
