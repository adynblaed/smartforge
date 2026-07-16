import { Link } from "@tanstack/react-router"
import { FaFacebookF, FaInstagram, FaLinkedinIn } from "react-icons/fa"
import { FaXTwitter } from "react-icons/fa6"

const socialLinks = [
  {
    icon: FaInstagram,
    href: "https://www.instagram.com/futureform_nv/",
    label: "Instagram",
  },
  {
    icon: FaFacebookF,
    href: "https://www.facebook.com/people/Future-Form/61585949411066/",
    label: "Facebook",
  },
  {
    icon: FaLinkedinIn,
    href: "https://www.linkedin.com/company/future-form-nv/?viewAsMember=true",
    label: "LinkedIn",
  },
  { icon: FaXTwitter, href: "https://x.com/FutureFormManu", label: "X" },
]

export function Footer() {
  return (
    <footer className="border-t px-6 py-8 text-sm">
      <div className="mx-auto flex max-w-6xl flex-col gap-8">
        <div className="flex flex-col gap-8 sm:flex-row sm:items-start sm:justify-between">
          {/* contact */}
          <address className="not-italic text-muted-foreground">
            <p className="font-semibold text-foreground">Future Form</p>
            <p>
              <a
                href="tel:+18008697222"
                className="transition-colors hover:text-foreground"
              >
                800-869-7222
              </a>
            </p>
            <p>
              <a
                href="mailto:sales@futureform.com"
                className="transition-colors hover:text-foreground"
              >
                sales@futureform.com
              </a>
            </p>
            <p>
              <a
                href="https://futureform.com"
                target="_blank"
                rel="noopener noreferrer"
                className="transition-colors hover:text-foreground"
              >
                https://futureform.com
              </a>
            </p>
            <p>599 E Nugget Ave., Sparks, NV 89431</p>
          </address>

          {/* socials */}
          <div className="flex items-center gap-4">
            {socialLinks.map(({ icon: Icon, href, label }) => (
              <a
                key={label}
                href={href}
                target="_blank"
                rel="noopener noreferrer"
                aria-label={label}
                className="text-muted-foreground transition-colors hover:text-foreground"
              >
                <Icon className="h-5 w-5" />
              </a>
            ))}
          </div>
        </div>

        <div className="flex flex-col items-center justify-between gap-3 border-t pt-4 text-xs sm:flex-row">
          <p className="text-muted-foreground">
            © 2026 Future Form Manufacturing, LLC. All rights reserved.
          </p>
          <div className="flex items-center gap-4">
            <Link
              to="/privacy"
              className="text-muted-foreground transition-colors hover:text-foreground"
            >
              Privacy Policy
            </Link>
            <Link
              to="/terms"
              className="text-muted-foreground transition-colors hover:text-foreground"
            >
              Terms &amp; Conditions
            </Link>
          </div>
        </div>
      </div>
    </footer>
  )
}
