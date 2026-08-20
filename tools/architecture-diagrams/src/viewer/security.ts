export function isSafeEmbeddedImageHref(href: string): boolean {
  return /^data:image\/(?:svg\+xml|png);base64,[A-Za-z0-9+/]+={0,2}$/.test(href);
}
