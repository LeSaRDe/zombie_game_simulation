export type NumericRule = {path: string; label: string; integer: boolean; minimum?: number; exclusiveMinimum?: boolean};

// These are the existing backend domains, not the editor's suggested increments.
export const configurationNumberRules: Record<string, NumericRule> = Object.fromEntries([
  {path:'seed', label:'Random seed', integer:true, minimum:0},
  {path:'horizon', label:'Run horizon', integer:false, minimum:0, exclusiveMinimum:true},
  {path:'incubation_duration', label:'Incubation duration', integer:false, minimum:0, exclusiveMinimum:true},
  {path:'world.length', label:'World length', integer:false, minimum:0, exclusiveMinimum:true},
  {path:'world.width', label:'World width', integer:false, minimum:0, exclusiveMinimum:true},
  {path:'population.humans', label:'Humans', integer:true, minimum:0},
  {path:'population.zombies', label:'Zombies', integer:true, minimum:0},
  {path:'population.infected', label:'Initially infected humans', integer:true, minimum:0},
  {path:'execution.workers', label:'Workers', integer:true, minimum:0, exclusiveMinimum:true},
].map(rule => [rule.path, rule]));

/** Preserve editable text until a caller explicitly commits a complete number. */
export function parseNumericText(text: string, rule: NumericRule): number {
  const invalid = (detail: string): never => {
    const message = `${rule.label}: ${detail}`;
    throw Object.assign(new Error(message), {code:'INVALID_DOMAIN',
      issues:[{path:rule.path, code:'INVALID_DOMAIN', message}]});
  };
  const input = text.trim();
  if (!input) return invalid('enter a number; this field is empty.');
  if (!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(input)) {
    return invalid('enter a complete number.');
  }
  const value = Number(input);
  if (!Number.isFinite(value)) return invalid('enter a finite number.');
  if (rule.integer && !Number.isInteger(value)) return invalid('enter a whole number.');
  if (rule.minimum !== undefined && (rule.exclusiveMinimum ? value <= rule.minimum : value < rule.minimum)) {
    return invalid(rule.minimum === 0
      ? rule.exclusiveMinimum ? 'enter a number greater than zero.' : 'enter zero or a positive number.'
      : `enter a number ${rule.exclusiveMinimum ? 'greater than' : 'at least'} ${rule.minimum}.`);
  }
  return value;
}
