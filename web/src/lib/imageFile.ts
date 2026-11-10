/** Downscale a picked image on the device before upload: faster on mobile data, and never sends huge originals. */
export async function fileToDataUrl(file: File, maxSide = 1600, quality = 0.85): Promise<string> {
  if (!file.type.startsWith("image/")) throw new Error("not_image");
  const bmp = await createImageBitmap(file);
  const k = Math.min(1, maxSide / Math.max(bmp.width, bmp.height));
  const c = document.createElement("canvas");
  c.width = Math.round(bmp.width * k);
  c.height = Math.round(bmp.height * k);
  c.getContext("2d")!.drawImage(bmp, 0, 0, c.width, c.height);
  bmp.close();
  return c.toDataURL("image/jpeg", quality);
}
