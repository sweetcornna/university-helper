/*
 * Accessible on/off switch. The previous inline version was a `relative` (not
 * flex) button with `min-h-[44px]` and an `inline-block` knob that was never
 * vertically centred, and it over-translated (translate-x-7 = 28px when only
 * ~24px of travel fit) — so the knob bulged out of the track. Here a 44px touch
 * target wraps a fixed 28×48 track whose 24px knob is flex-centred and travels
 * exactly track-inner-width − knob-width (44 − 24 = 20px = translate-x-5).
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
      className="inline-flex min-h-[44px] min-w-[44px] items-center justify-center rounded-full p-1.5 cursor-pointer transition-opacity focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 disabled:cursor-not-allowed disabled:opacity-50"
    >
      <span
        className={`relative inline-flex h-7 w-12 items-center rounded-full px-0.5 transition-colors duration-200 ${
          checked ? 'bg-primary' : 'bg-border'
        }`}
      >
        <span
          className={`inline-block h-6 w-6 rounded-full bg-white shadow-sm transition-transform duration-200 ${
            checked ? 'translate-x-5' : 'translate-x-0'
          }`}
        />
      </span>
    </button>
  )
}
