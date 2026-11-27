import {modelCatalog} from './modelSelection';
type Obj = Record<string, any>;

const isObject = (value: unknown): value is Obj => value !== null && typeof value === 'object' && !Array.isArray(value);
const invalid = (message: string) => Object.assign(new Error(message), {code: 'INVALID_CONFIGURATION'});

/** Check the editor's transport contract; the backend owns simulation validation. */
export function configurationMetadata(value: unknown): Obj {
  const fail = () => { throw invalid('The service returned incomplete or unsupported configuration metadata. Retry loading configuration.'); };
  if (!isObject(value) || value.schema_version !== 'zombie-sim/config-v1' || !isObject(value.presets)) return fail();
  if (!isObject(value.presets.small) || !Object.keys(value.presets.small).length ||
      !isObject(value.presets.baseline) || !Object.keys(value.presets.baseline).length) return fail();
  if (!Array.isArray(value.fields) || !value.fields.length) return fail();
  const paths = new Set<string>();
  for (const field of value.fields) {
    if (!isObject(field) || typeof field.path !== 'string' ||
        !/^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$/.test(field.path) ||
        field.path.split('.').some((part: string) => ['__proto__', 'prototype', 'constructor'].includes(part)) ||
        typeof field.label !== 'string' || !field.label.trim() || !['text', 'integer', 'number'].includes(field.type) ||
        (field.min !== undefined && (typeof field.min !== 'number' || !Number.isFinite(field.min))) ||
        (field.unit !== undefined && typeof field.unit !== 'string') || paths.has(field.path)) return fail();
    paths.add(field.path);
    // A nested editor path must not descend through a scalar or array. Missing
    // values remain allowed, including the existing omitted model default.
    for (const preset of [value.presets.small, value.presets.baseline]) {
      let parent: any = preset;
      for (const part of field.path.split('.').slice(0, -1)) {
        if (parent[part] === undefined) break;
        if (!isObject(parent[part])) return fail();
        parent = parent[part];
      }
    }
  }
  for (const preset of [value.presets.small, value.presets.baseline]) {
    for (const key of ['execution', 'placement', 'storage']) {
      if (preset[key] !== undefined && !isObject(preset[key])) return fail();
    }
  }
  modelCatalog(value.models);
  return value;
}

/** All actions consume the same draft text without rewriting it on failure. */
export function parseConfigurationDraft(text: string): Obj {
  if (!text.trim()) throw invalid('Enter a complete JSON configuration before continuing. The Advanced JSON editor is empty.');
  let parsed: unknown;
  try { parsed = JSON.parse(text); }
  catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    throw invalid(`Enter a complete JSON configuration. JSON could not be read: ${detail}`);
  }
  if (!isObject(parsed)) throw invalid('The configuration must be a JSON object, such as { ... }, rather than an array, null, or a single value.');
  return parsed;
}
