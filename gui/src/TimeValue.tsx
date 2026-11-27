import {InputHTMLAttributes, ReactNode, useId, useState} from 'react';
import {formatTime} from './timeFormat';
import './timeFormat.css';

export function TimeValue({value, unit = true, details = true, className = ''}: {
  value: unknown; unit?: boolean; details?: boolean; className?: string;
}) {
  const time = formatTime(value), [open, setOpen] = useState(false), detailId = useId();
  return <span className={`time-value ${className}`} data-exact-time={time.valid ? time.exact : undefined}
    title={time.valid ? `Exact time: ${time.exact} seconds` : undefined}>
    <span className="time-label">{time.label}{unit && time.valid ? ' s' : ''}</span>
    {details && time.valid && <>
      <button type="button" className="time-detail-toggle" aria-expanded={open} aria-controls={detailId}
        onClick={event => {event.stopPropagation(); setOpen(current => !current);}}>Exact time</button>
      <span className="time-exact-text" id={detailId} hidden={!open}><code>{time.exact}</code> s</span>
    </>}
  </span>;
}

type ExactTimeInputProps = Omit<InputHTMLAttributes<HTMLInputElement>, 'value'> & {
  label: ReactNode; value: string; 'data-testid'?: string;
};

/** The summary is display-only; the existing input value remains authoritative. */
export function ExactTimeInput({label, value, ...inputProps}: ExactTimeInputProps) {
  const testId = inputProps['data-testid'];
  const time = formatTime(value);
  return <details className="exact-time-editor" data-testid={testId ? `${testId}-editor` : undefined}>
    <summary data-testid={testId ? `${testId}-toggle` : undefined}>
      <span className="exact-time-label">{label}</span>{' '}
      <span className="time-label" data-exact-time={time.valid ? time.exact : undefined}>
        {time.label}{time.valid ? ' s' : ''}
      </span>{' '}<span className="exact-time-edit-hint">Edit exact time</span>
    </summary>
    <label className="exact-time-input-label">{label}<input {...inputProps} value={value}/></label>
  </details>;
}

export default TimeValue;
