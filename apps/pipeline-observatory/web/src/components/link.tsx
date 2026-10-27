import type { AnchorHTMLAttributes, MouseEvent } from "react";
import { navigate } from "../router";
import { hrefFor } from "../routes";

interface Props extends Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href"> { to: string }

/** In-app link: a real <a href> (works without JS and in a new tab), client-side on a plain click. `to` is a route path, optionally with a query. */
export function Link({ to, onClick, ...rest }: Props) {
  const href = hrefFor(to);
  const handle = (e: MouseEvent<HTMLAnchorElement>): void => {
    onClick?.(e);
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    navigate(href);
  };
  return <a {...rest} href={href} onClick={handle} />;
}
