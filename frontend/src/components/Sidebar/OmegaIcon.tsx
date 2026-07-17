import { forwardRef } from "react"

/**
 * Omega (Ω) glyph drawn in the lucide stroke style (24×24 grid, 2px round
 * strokes) so it sits seamlessly next to the lucide icons in the sidebar.
 */
export const OmegaIcon = forwardRef<
  SVGSVGElement,
  React.SVGProps<SVGSVGElement>
>((props, ref) => (
  <svg
    ref={ref}
    xmlns="http://www.w3.org/2000/svg"
    width="24"
    height="24"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
    {...props}
  >
    <path d="M9 19.5H4.8v-1.6c2.6-1.6 4.2-4.5 4.2-7.4a4.5 4.5 0 1 1 6 0c0 2.9 1.6 5.8 4.2 7.4v1.6H15" />
  </svg>
))
OmegaIcon.displayName = "OmegaIcon"
