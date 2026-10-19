export function usableGalleryPins(pins, failed = {}, termId = '') {
  const ids = new Set(), images = new Set();
  return (pins || []).filter(pin => {
    if (pin.status !== 'available' || !pin.thumbnail_url || failed[`${termId}:${pin.pin_id}`]
      || ids.has(pin.pin_id) || images.has(pin.thumbnail_url)) return false;
    ids.add(pin.pin_id); images.add(pin.thumbnail_url); return true;
  }).slice(0,8);
}
