import {percentageLabel, readRoleGroups, realizedLabel, roleEditingBlock, roleKinds, roleLabel, roleOrder, targetMatchesCount} from './roleAllocation';
import {parseConfigurationDraft} from './configurationDraft';

export default function RoleAllocationPanels({advanced,presets,text,errors,populationPending,onEdit,onCommit}:{
  advanced:string;presets:Record<string,any>;text:Record<string,string>;errors:Record<string,string>;populationPending:boolean;
  onEdit:(path:string,text:string)=>void;onCommit:()=>void;
}) {
  let config,groups;
  try{config=parseConfigurationDraft(advanced);groups=readRoleGroups(config,presets);}
  catch(error){return <section className="role-allocation"><h3>Role percentages</h3><p className="config-field-error" data-testid="role-allocation-error">{(error as Error).message}</p><p>Correct the configuration to display its role allocations.</p></section>;}
  const blocked=roleEditingBlock(config);
  const pending=populationPending||Object.keys(text).length>0;
  return <section className="role-allocation" aria-label="Role percentages"><h3>Role percentages</h3><p>Set target shares for each population. Whole-agent counts update together when you leave a valid field. Remaining agents have no active role.</p>
    {blocked&&<p className="notice" data-testid="role-explicit-agents">{blocked}</p>}
    {pending&&<p className="role-pending" role="status">Edits pending. Counts and realized shares below show the last committed configuration until all entries are valid.</p>}
    {roleKinds.map(kind=>{const group=groups[kind];return <section className="role-type" key={kind} data-testid={`role-panel-${kind}`} aria-label={`${kind} role allocation`}>
      <h4>{kind} roles <span>{group.total} {kind==='Human'?'humans':'zombies'}</span></h4>
      {errors[kind]&&<p className="config-field-error" role="alert">{errors[kind]}</p>}
      <table><caption className="sr-only">{kind} role target percentages and integer counts</caption><thead><tr><th scope="col">Role</th><th scope="col">Target %</th><th scope="col">Agents</th><th scope="col">Realized %</th></tr></thead><tbody>
        {roleOrder[kind].map(role=>{const key=`${kind}.${role}`;const label=percentageLabel(group.targets[role]);const error=errors[key];const errorId=`role-error-${kind}-${role}`;return <tr key={role}>
          <th scope="row">{roleLabel(role)}</th><td data-testid={`role-target-${kind}-${role}`}>
            {role==='unassigned'?<span>{label.approximate?'≈ ':''}{label.text}% <small>automatic</small></span>:<><label className="sr-only" htmlFor={`role-${kind}-${role}`}>{kind} {roleLabel(role)} target percentage</label><input id={`role-${kind}-${role}`} data-testid={`role-${kind}-${role}`} type="text" inputMode="decimal" disabled={Boolean(blocked)} value={Object.prototype.hasOwnProperty.call(text,key)?text[key]:label.text} aria-invalid={Boolean(error)} aria-describedby={error?errorId:undefined} onChange={event=>onEdit(key,event.target.value)} onBlur={onCommit}/>{label.approximate&&!Object.prototype.hasOwnProperty.call(text,key)&&<small title={`Exact target share ${group.targets[role].numerator}/${group.targets[role].denominator}; the rounded label is not used for calculation.`}>≈ displayed; exact ratio retained</small>}{error&&<span id={errorId} className="config-field-error">{error}</span>}</>}
          </td><td data-testid={`role-count-${kind}-${role}`}>{group.counts[role]}</td><td data-testid={`role-realized-${kind}-${role}`} className={group.total&&!targetMatchesCount(group.targets[role],group.counts[role],group.total)?'role-rounded':''}>{realizedLabel(group.counts[role],group.total)}</td>
        </tr>;})}
      </tbody><tfoot><tr><th scope="row">Total</th><td>100%</td><td data-testid={`role-total-${kind}`}>{group.total}</td><td>{group.total?'100%':'—'}</td></tr></tfoot></table>
    </section>;})}
    <p className="role-rounding-note">Small populations may realize different percentages: 10% of seven can become one agent (≈ 14.29%). Allocation uses largest remainders; equal remainders follow the displayed role order. Initially infected humans remain part of the Human total.</p>
  </section>;
}
