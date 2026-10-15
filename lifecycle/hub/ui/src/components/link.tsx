import type { JSX } from "preact";
import { navigate } from "../router";

type Props = JSX.HTMLAttributes<HTMLAnchorElement> & { href: string };

/** An anchor that updates the UI in place instead of reloading the page. */
export function Link({ href, children, ...rest }: Props) {
  return (
    <a
      href={href}
      {...rest}
      onClick={(event) => {
        if (event.defaultPrevented || event.button !== 0) return;
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        navigate(href);
      }}
    >
      {children}
    </a>
  );
}
