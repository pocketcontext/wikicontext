"""Validate reviewed image evidence locally before any immutable writes."""
import hashlib
import io
import json
from pathlib import Path
import re
import warnings

from . import cli as wc

EXTENSIONS = {'.png': 'PNG', '.jpg': 'JPEG', '.jpeg': 'JPEG', '.webp': 'WEBP'}
MAX_PIXELS = 50_000_000
MAX_DIMENSION = 16384
MAX_REVIEW = 8 * 1024 * 1024


def fail(message):
    raise wc.Fail(2, 'Image review: ' + message)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def prepare(content, suffix, review_path):
    if not review_path:
        fail('supply --image-review JSON with reviewed passages; no upload attempted.')
    try:
        from PIL import Image
    except ImportError:
        fail('Pillow is required for local PNG/JPEG/WebP validation; install it in your Python environment.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as image:
                image_format = image.format
                width, height = image.size
                if image_format != EXTENSIONS[suffix]:
                    fail('file extension does not match its actual image format.')
                if not 0 < width <= MAX_DIMENSION or not 0 < height <= MAX_DIMENSION or width * height > MAX_PIXELS:
                    fail('image exceeds 16384 pixels per axis or 50 million decoded pixels.')
                if getattr(image, 'n_frames', 1) != 1:
                    fail('animated or multi-frame images are unsupported; provide explicit static sources.')
                image.verify()
            with Image.open(io.BytesIO(content)) as image:
                image.load()
    except wc.Fail:
        raise
    except Exception:
        fail('image cannot be verified and decoded safely; no upload attempted.')
    try:
        path = Path(review_path)
        if path.stat().st_size > MAX_REVIEW:
            fail('JSON exceeds 8 MiB.')
        with path.open('rb') as handle:
            raw = handle.read(MAX_REVIEW + 1)
        if len(raw) > MAX_REVIEW:
            fail('JSON exceeds 8 MiB.')
        review = json.loads(raw, object_pairs_hook=unique_object)
    except (OSError, ValueError, TypeError):
        fail('cannot read valid UTF-8 review JSON (duplicate keys are forbidden).')
    required = {'processor', 'source_sha256', 'width', 'height', 'passages'}
    optional = {'related_source', 'sequence', 'notes'}
    if not isinstance(review, dict) or not required <= review.keys() or review.keys() - required - optional:
        fail('expected processor, source_sha256, width, height, passages and optional related_source, sequence, notes.')
    processor = review['processor']
    if not isinstance(processor, str) or not processor.strip() or len(processor) > 300:
        fail('processor must contain 1–300 characters identifying the reviewer/model and extraction process.')
    digest = hashlib.sha256(content).hexdigest()
    if review['source_sha256'] != digest:
        fail('source_sha256 does not match the original bytes.')
    if type(review['width']) is not int or type(review['height']) is not int or (review['width'], review['height']) != (width, height):
        fail('width and height must match the encoded image dimensions before EXIF rotation.')
    if 'related_source' in review and (not isinstance(review['related_source'], str) or not re.fullmatch(r'[a-z0-9]{15}', review['related_source'])):
        fail('related_source must be a 15-character source record ID.')
    if 'sequence' in review and (type(review['sequence']) is not int or not 1 <= review['sequence'] <= 1_000_000):
        fail('sequence must be an integer from 1 to 1000000, not a timestamp.')
    if 'sequence' in review and 'related_source' not in review:
        fail('sequence requires related_source.')
    if 'notes' in review and (not isinstance(review['notes'], str) or len(review['notes']) > 2000):
        fail('notes must be a string no longer than 2000 characters.')
    items = review['passages']
    if not isinstance(items, list) or not 1 <= len(items) <= 1000:
        fail('passages must contain 1–1000 reviewed items.')
    passages = []
    for item in items:
        if not isinstance(item, dict) or set(item) != {'kind', 'body', 'region'}:
            fail('each passage requires exactly kind, body and region.')
        if item['kind'] not in ('transcription', 'description', 'caption'):
            fail('passage kind must be transcription, description or caption.')
        body = item['body']
        if not isinstance(body, str) or not body.strip() or len(body) > 24000:
            fail('passage body must contain 1–24000 characters.')
        region = item['region']
        if not isinstance(region, list) or len(region) != 4 or any(type(v) is not int for v in region):
            fail('region must be four integer pixel coordinates [x, y, width, height].')
        x, y, w, h = region
        if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > width or y + h > height:
            fail('region must fit inside the original encoded image.')
        locator = json.dumps({'kind': item['kind'], 'region': region, 'units': 'pixels', 'orientation': 'encoded'}, sort_keys=True)
        passages.append({'locator': locator, 'body': body})
    canonical = json.dumps(review, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    try:
        review_digest = hashlib.sha256(canonical.encode()).hexdigest()
    except UnicodeEncodeError:
        fail('review text must contain valid Unicode characters.')
    provenance = {'source_sha256': digest, 'width': width, 'height': height, 'format': image_format,
                  'review_sha256': review_digest, 'processor': processor,
                  **{key: review[key] for key in optional if key in review}}
    return processor, passages, provenance
