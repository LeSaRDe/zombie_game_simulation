import {useState} from 'react';
import {parseConfigurationDraft} from './configurationDraft';
import {ModelCatalog, ModelField, ModelKind, modelField, modelKinds, modelRequestId, readModelSetting} from './modelSelection';

export default function ModelSelection({advanced,catalog,onChange}:{advanced:string;catalog:ModelCatalog;onChange:(field:ModelField,value:string)=>void}){
  const [advancedOpen,setAdvancedOpen]=useState<Partial<Record<ModelKind,boolean>>>({});
  let config;
  try{config=parseConfigurationDraft(advanced);for(const kind of modelKinds)readModelSetting(config,kind,catalog);}
  catch(error){return <section className="model-selection" data-testid="model-selection"><h3>Decision models</h3><p className="config-field-error" data-testid="model-selection-error">{(error as Error).message}</p><p>Correct Advanced JSON to inspect or change its decision models.</p></section>;}
  return <section className="model-selection" data-testid="model-selection" aria-label="Decision models">
    <h3>Decision models</h3><p>A model chooses actions from each agent’s local observations and private memory. A role, such as Doctor or Runner, determines capabilities; it is a separate setting.</p>
    {modelKinds.map(kind=>{
      const field=modelField(kind),setting=readModelSetting(config,kind,catalog);
      const choices=catalog.choices.filter(choice=>choice.applicable_types.includes(kind));
      const custom=Boolean(advancedOpen[kind]||!setting.choice||!setting.compatible);
      const selected=setting.explicitAgents?'__explicit__':custom?'__advanced__':setting.choice!.model_id;
      const input=typeof setting.request==='string'?setting.request:JSON.stringify(setting.request)??'';
      const error=typeof setting.request!=='string'?'The supplied model ID is not text. Choose a listed model or enter a registered model ID.'
        :!setting.request.trim()?'Enter a registered model ID or choose a listed model; an explicit empty value is not the default.':undefined;
      const statusId=`model-${field}-status`,errorId=`model-${field}-error`,helpId=`model-${field}-help`;
      return <div className="model-setting" key={kind} data-testid={`model-${field}`}>
        <label htmlFor={`model-${field}-select`}>{kind} decision model</label>
        <select id={`model-${field}-select`} aria-label={`${kind} decision model`} data-testid={`config-${field}`} disabled={Boolean(setting.blocked)} value={selected}
          aria-describedby={`${helpId} ${statusId}${error?` ${errorId}`:''}`} onChange={event=>{
            if(event.target.value==='__advanced__'){setAdvancedOpen(value=>({...value,[kind]:true}));return;}
            const choice=choices.find(item=>item.model_id===event.target.value);
            if(choice){onChange(field,modelRequestId(choice,kind,catalog));setAdvancedOpen(value=>({...value,[kind]:false}));}
          }}>
          {setting.explicitAgents&&<option value="__explicit__">Per-agent assignments · edit Advanced JSON</option>}
          {choices.map(choice=><option key={choice.model_id} value={choice.model_id}>{choice.label} — {modelRequestId(choice,kind,catalog)} · {choice.version}</option>)}
          <option value="__advanced__">Advanced registered model or artifact</option>
        </select>
        {setting.blocked&&<p className="notice" data-testid={`model-${field}-blocked`}>{setting.blocked}</p>}
        {setting.explicitAgents?<p id={statusId} data-testid={statusId}>{setting.assignments.length?`Initial ${kind} assignments: ${setting.assignments.join('; ')}.`:`No explicit ${kind} agents in this draft.`} Existing per-agent versions and parameters are retained.</p>:<>
          {custom&&<label className="model-advanced" htmlFor={`model-${field}-advanced`}>{kind} registered model ID or artifact
            <input id={`model-${field}-advanced`} data-testid={`config-${field}-advanced`} type="text" value={input} disabled={Boolean(setting.blocked)} aria-invalid={Boolean(error)} aria-describedby={`${statusId}${error?` ${errorId}`:''}`} onChange={event=>onChange(field,event.target.value)}/>
          </label>}
          {error&&<p className="config-field-error" id={errorId} data-testid={errorId}>{error}</p>}
          <p id={statusId} data-testid={statusId}>
            {setting.omitted?'Default inherited; the configuration key remains omitted. ':`Requested ID: ${input||'(empty)'}. `}
            {setting.choice?<>Registered identity: <code>{setting.choice.model_id}</code> · installed version {setting.choice.version}.
              {!setting.compatible&&<> Declared for {setting.choice.applicable_types.join(' / ')}; choose a compatible {kind} policy.</>}
            </>:typeof setting.request==='string'&&setting.request.startsWith('ppo:')?'Artifact identity and version are checked when you validate; weights are not loaded to show this list.'
              :typeof setting.request==='string'&&catalog.registered_names.includes(setting.request)?'Registered plugin; descriptive/version metadata is unavailable. Validate before launching.'
              :!error?'This ID is not listed in this service’s registry. Validate to check availability, or choose a listed model.':null}
          </p>
          {setting.choice&&<p className="model-description">{setting.choice.description}</p>}
        </>}
        <p id={helpId} className="model-help">{custom&&!setting.explicitAgents?'A plugin must be registered in the service. For a trained artifact, enter ppo:<artifact-directory>; its files and dependencies must exist on the service machine. Typing a name does not create a model. Validate before preview or launch.':'Changing a choice applies to this new experiment. Imported aliases and omitted defaults stay unchanged until you edit them.'}</p>
      </div>;
    })}
  </section>;
}
