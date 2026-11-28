import {ObservableController} from './ObservableController';
import {RequestTransport} from './contracts';
import {Obj,Bundle,api as defaultApi,id,download} from '../uiRuntime';
import {configurationMetadata,parseConfigurationDraft} from '../configurationDraft';
import {configurationNumberRules,parseNumericText} from '../numericDraft';
import {applyRoleEdits,roleEditingBlock,parseRolePercentage,readRoleGroups} from '../roleAllocation';
import {ModelField,readModelSetting} from '../modelSelection';
import {applyWorldResize} from '../worldLayout';
export interface ConfigurationCallbacks {onClose():void;onCreated(id:string,generation?:number):void;onStartState(id:string,pending:boolean,generation?:number,uncertain?:boolean):void;onError(text:string):void}
/** Owns the atomic editable draft, validation and experiment creation workflow. */
export class ConfigurationEditor extends ObservableController {
 metadata:Obj|undefined=undefined;
 setMetadata=(value:Obj|undefined|((previous:Obj|undefined)=>Obj|undefined))=>{this.metadata=typeof value==='function'?(value as (previous:Obj|undefined)=>Obj|undefined)(this.metadata):value;this.changed();};
 draft:Obj={};
 setDraft=(value:Obj|((previous:Obj)=>Obj))=>{this.draft=typeof value==='function'?(value as (previous:Obj)=>Obj)(this.draft):value;this.changed();};
 advanced:string='';
 setAdvanced=(value:string|((previous:string)=>string))=>{this.advanced=typeof value==='function'?(value as (previous:string)=>string)(this.advanced):value;this.changed();};
 preview:Bundle|undefined=undefined;
 setPreview=(value:Bundle|undefined|((previous:Bundle|undefined)=>Bundle|undefined))=>{this.preview=typeof value==='function'?(value as (previous:Bundle|undefined)=>Bundle|undefined)(this.preview):value;this.changed();};
 result:string='';
 setResult=(value:string|((previous:string)=>string))=>{this.result=typeof value==='function'?(value as (previous:string)=>string)(this.result):value;this.changed();};
 issues:Obj[]=[];
 setIssues=(value:Obj[]|((previous:Obj[])=>Obj[]))=>{this.issues=typeof value==='function'?(value as (previous:Obj[])=>Obj[])(this.issues):value;this.changed();};
 artifactId:string='';
 setArtifactId=(value:string|((previous:string)=>string))=>{this.artifactId=typeof value==='function'?(value as (previous:string)=>string)(this.artifactId):value;this.changed();};
 exportFormat:string='json';
 setExportFormat=(value:string|((previous:string)=>string))=>{this.exportFormat=typeof value==='function'?(value as (previous:string)=>string)(this.exportFormat):value;this.changed();};
 busy:boolean=false;
 setBusy=(value:boolean|((previous:boolean)=>boolean))=>{this.busy=typeof value==='function'?(value as (previous:boolean)=>boolean)(this.busy):value;this.changed();};
 batchSeeds:string='';
 setBatchSeeds=(value:string|((previous:string)=>string))=>{this.batchSeeds=typeof value==='function'?(value as (previous:string)=>string)(this.batchSeeds):value;this.changed();};
 modelEditorVersion:number=0;
 setModelEditorVersion=(value:number|((previous:number)=>number))=>{this.modelEditorVersion=typeof value==='function'?(value as (previous:number)=>number)(this.modelEditorVersion):value;this.changed();};
 numericText:Record<string,string>={};
 setNumericText=(value:Record<string,string>|((previous:Record<string,string>)=>Record<string,string>))=>{this.numericText=typeof value==='function'?(value as (previous:Record<string,string>)=>Record<string,string>)(this.numericText):value;this.changed();};
 numericErrors:Record<string,string>={};
 setNumericErrors=(value:Record<string,string>|((previous:Record<string,string>)=>Record<string,string>))=>{this.numericErrors=typeof value==='function'?(value as (previous:Record<string,string>)=>Record<string,string>)(this.numericErrors):value;this.changed();};
 roleText:Record<string,string>={};
 setRoleText=(value:Record<string,string>|((previous:Record<string,string>)=>Record<string,string>))=>{this.roleText=typeof value==='function'?(value as (previous:Record<string,string>)=>Record<string,string>)(this.roleText):value;this.changed();};
 roleErrors:Record<string,string>={};
 setRoleErrors=(value:Record<string,string>|((previous:Record<string,string>)=>Record<string,string>))=>{this.roleErrors=typeof value==='function'?(value as (previous:Record<string,string>)=>Record<string,string>)(this.roleErrors):value;this.changed();};
 loadState:{phase:'loading'|'ready'|'failed';error?:string}={phase:'loading'};
 setLoadState=(value:{phase:'loading'|'ready'|'failed';error?:string}|((previous:{phase:'loading'|'ready'|'failed';error?:string})=>{phase:'loading'|'ready'|'failed';error?:string}))=>{this.loadState=typeof value==='function'?(value as (previous:{phase:'loading'|'ready'|'failed';error?:string})=>{phase:'loading'|'ready'|'failed';error?:string})(this.loadState):value;this.changed();};
 draftRef={current:this.draft};
 advancedRef={current:this.advanced};
 numericTextRef={current:this.numericText};
 numericErrorsRef={current:this.numericErrors};
 roleTextRef={current:this.roleText};
 roleErrorsRef={current:this.roleErrors};
 loadStateRef={current:this.loadState};
 busyRef={current:this.busy};
 private controller?:AbortController;private loadVersion=0;private source?:Obj;
 private readonly id=id;private readonly download=download;
 constructor(public callbacks:ConfigurationCallbacks,private readonly api:RequestTransport=defaultApi,private readonly storage:Pick<Storage,'getItem'|'setItem'>=localStorage){super();}
 get ready(){return this.loadState.phase==='ready';}get unavailable(){return !this.ready||this.busy;}
 load=(source?:Obj)=>{this.source=source;this.controller?.abort();const controller=this.controller=new AbortController();const version=++this.loadVersion;this.setLoadingState({phase:'loading'});this.setMetadata(undefined);this.api('/config',undefined,controller.signal).then(configurationMetadata).then(data=>{if(controller.signal.aborted||version!==this.loadVersion)return;this.setMetadata(data);this.replaceDraft(structuredClone(source||data.presets.small));this.setLoadingState({phase:'ready'});}).catch((error:Error)=>{if(!controller.signal.aborted&&version===this.loadVersion)this.setLoadingState({phase:'failed',error:error.message});});};
 retry=()=>this.load(this.source);
 dispose=()=>{this.controller?.abort();this.loadVersion++;};
setLoadingState = (state: typeof this.loadState) => { this.loadStateRef.current = state; this.setLoadState(state); };
clearDraftFeedback = () => { this.setPreview(undefined); this.setArtifactId(''); this.setResult(''); this.setIssues([]); };
setDraftValue = (config: Obj) => { this.draftRef.current = config; this.setDraft(config); };
setAdvancedValue = (text: string) => { this.advancedRef.current = text; this.setAdvanced(text); };
setNumericState = (text: Record<string, string>, errors: Record<string, string>) => {
    this.numericTextRef.current = text;
    this.setNumericText(text);
    this.numericErrorsRef.current = errors;
    this.setNumericErrors(errors);
};
setRoleState = (text: Record<string, string>, errors: Record<string, string>) => { this.roleTextRef.current = text; this.setRoleText(text); this.roleErrorsRef.current = errors; this.setRoleErrors(errors); };
replaceDraft = (config: Obj) => { this.setDraftValue(config); this.setAdvancedValue(JSON.stringify(config, null, 2)); this.setNumericState({}, {}); this.setRoleState({}, {}); this.setModelEditorVersion(value => value + 1); this.clearDraftFeedback(); };
reportDraftError = (error: any) => { this.setResult(error.message); this.setIssues(error.issues || [{ path: 'configuration', code: error.code || 'INVALID_REQUEST', message: error.message }]); };
requireReady = () => {
    if (this.loadStateRef.current.phase !== 'ready')
        throw Error('Wait for configuration to finish loading, or retry if loading failed.');
};
numericFailure = (errors: Record<string, string>) => Object.assign(new Error(Object.values(errors).join(' ')), {
    code: 'INVALID_DOMAIN', issues: Object.entries(errors).map(([key, message]) => { const path = /^(Human|Zombie)\./.test(key) ? `gui.role_allocation.${key.replace('.', '.targets.')}` : key === 'Human' || key === 'Zombie' ? `gui.role_allocation.${key}` : key; return { path, code: 'INVALID_DOMAIN', message }; })
});
retainNumericFeedback = () => { const errors = { ...this.numericErrorsRef.current, ...this.roleErrorsRef.current }; if (Object.keys(errors).length)
    this.reportDraftError(this.numericFailure(errors)); };
assignPath = (config: Obj, path: string, value: any) => {
    const keys = path.split('.');
    let node = config;
    for (const key of keys.slice(0, -1)) {
        if (node[key] === undefined)
            node[key] = {};
        if (node[key] === null || typeof node[key] !== 'object' || Array.isArray(node[key]))
            throw Error(`${path}: correct its containing object in Advanced JSON before editing this field.`);
        node = node[key];
    }
    node[keys.at(-1)!] = value;
};
readDraft = () => {
    this.requireReady();
    const config = parseConfigurationDraft(this.advancedRef.current);
    const base = structuredClone(config);
    const pending = this.numericTextRef.current;
    const parsed: Record<string, number> = {};
    const errors: Record<string, string> = {};
    for (const [path, text] of Object.entries(pending)) {
        try {
            parsed[path] = parseNumericText(text, configurationNumberRules[path]);
        }
        catch (error) {
            errors[path] = (error as Error).message;
        }
    }
    const rolePending = this.roleTextRef.current;
    const nextRoleErrors: Record<string, string> = {};
    for (const [path, text] of Object.entries(rolePending)) {
        try {
            parseRolePercentage(text, `gui.role_allocation.${path.replace('.', '.targets.')}`);
        }
        catch (error) {
            nextRoleErrors[path] = (error as Error).message;
        }
    }
    if (Object.keys(errors).length || Object.keys(nextRoleErrors).length) {
        this.setNumericState(pending, errors);
        this.setRoleState(rolePending, nextRoleErrors);
        throw this.numericFailure({ ...errors, ...nextRoleErrors });
    }
    // Commit all pending values together, from current refs rather than a render
    // closure. A pointer click can blur an input before its action handler runs.
    for (const [path, value] of Object.entries(parsed))
        this.assignPath(config, path, value);
    applyWorldResize(base, config, parsed, this.metadata!.presets);
    const populationBlock = roleEditingBlock(base);
    if (populationBlock && Object.keys(parsed).some(path => path.startsWith('population.')))
        throw Error(populationBlock);
    try {
        applyRoleEdits(base, config, rolePending, new Set(Object.keys(parsed).filter(path => path === 'population.humans' || path === 'population.zombies').map(path => path.split('.')[1])), this.metadata!.presets);
    }
    catch (error: any) {
        const path = error.issues?.[0]?.path || '';
        const kind = path.includes('Human') || path.includes('human') ? 'Human' : path.includes('Zombie') || path.includes('zombie') ? 'Zombie' : 'configuration';
        this.setRoleState(rolePending, { [kind]: error.message });
        throw error;
    }
    this.setDraftValue(config);
    this.setNumericState({}, {});
    this.setRoleState({}, {});
    if (Object.keys(pending).length || Object.keys(rolePending).length)
        this.setAdvancedValue(JSON.stringify(config, null, 2));
    return config;
};
editNumber = (path: string, text: string) => {
    if (this.loadStateRef.current.phase !== 'ready' || this.busyRef.current)
        return;
    const errors = { ...this.numericErrorsRef.current };
    delete errors[path];
    this.setNumericState({ ...this.numericTextRef.current, [path]: text }, errors);
    this.clearDraftFeedback();
    this.retainNumericFeedback();
};
editRole = (path: string, text: string) => {
    if (this.loadStateRef.current.phase !== 'ready' || this.busyRef.current)
        return;
    const errors = { ...this.roleErrorsRef.current };
    delete errors[path];
    delete errors[path.split('.')[0]];
    this.setRoleState({ ...this.roleTextRef.current, [path]: text }, errors);
    this.clearDraftFeedback();
    this.retainNumericFeedback();
};
commitNumbers = () => {
    if (this.loadStateRef.current.phase !== 'ready' || this.busyRef.current || (!Object.keys(this.numericTextRef.current).length && !Object.keys(this.roleTextRef.current).length))
        return;
    try {
        this.readDraft();
        this.clearDraftFeedback();
    }
    catch (error) {
        this.reportDraftError(error);
    }
};
change = (path: string, value: any) => {
    if (this.loadStateRef.current.phase !== 'ready' || this.busyRef.current)
        return;
    try {
        const next = parseConfigurationDraft(this.advancedRef.current);
        this.assignPath(next, path, value);
        if (path === 'execution.workers') {
            const text = { ...this.numericTextRef.current };
            const errors = { ...this.numericErrorsRef.current };
            delete text[path];
            delete errors[path];
            this.setNumericState(text, errors);
        }
        this.setDraftValue(next);
        this.setAdvancedValue(JSON.stringify(next, null, 2));
        this.clearDraftFeedback();
        this.retainNumericFeedback();
    }
    catch (error) {
        this.reportDraftError(error);
    }
};
editAdvanced = (text: string) => {
    // Complete JSON is the shared configuration immediately. Keep unfinished
    // text separate, so field edits cannot overwrite it with the last valid object.
    this.setAdvancedValue(text);
    this.setNumericState({}, {});
    this.setRoleState({}, {});
    this.clearDraftFeedback();
    try {
        this.setDraftValue(parseConfigurationDraft(text));
    }
    catch { /* Keep the last valid object for explicit discard. */ }
};
changeModel = (field: ModelField, value: string) => {
    if (this.loadStateRef.current.phase !== 'ready' || this.busyRef.current)
        return;
    try {
        // Model controls consume the current JSON, preserving imported aliases,
        // per-agent parameters and unrelated Advanced JSON edits until changed.
        const next = parseConfigurationDraft(this.advancedRef.current);
        const setting = readModelSetting(next, field === 'human_model' ? 'Human' : 'Zombie', this.metadata!.models);
        if (setting.blocked)
            throw Error(setting.blocked);
        next[field] = value;
        this.setDraftValue(next);
        this.setAdvancedValue(JSON.stringify(next, null, 2));
        this.clearDraftFeedback();
        this.retainNumericFeedback();
    }
    catch (error) {
        this.reportDraftError(error);
    }
};
action = async (kind: string) => {
    if (this.busyRef.current)
        return;
    let config: Obj;
    try {
        config = this.readDraft();
    }
    catch (error) {
        this.reportDraftError(error);
        return;
    }
    this.busyRef.current = true;
    this.setBusy(true);
    let handedOff = false;
    try {
        this.setDraftValue(config);
        if (kind === 'start') {
            const validated = await this.api('/config/validate', config);
            const seeds = this.batchSeeds.trim() ? this.batchSeeds.split(',').map(v => v.trim() ? Number(v.trim()) : NaN) : [validated.resolved.seed];
            if (seeds.length > 8 || seeds.some(seed => !Number.isInteger(seed) || seed < 0))
                throw Error('Enter at most eight nonnegative integer seeds.');
            for (const seed of seeds) {
                const run = await this.api('/runs', { config: { ...validated.resolved, seed }, command_id: this.id(), start: true, wait_for_initialization: false });
                this.callbacks.onStartState(run.run_id, true);
                if (!handedOff) {
                    handedOff = true;
                    this.callbacks.onCreated(run.run_id);
                    this.callbacks.onClose();
                }
                // Initialization belongs to the selected run screen. A late start
                // acknowledgement updates controls without reselecting that run.
                let ack: Obj;
                try {
                    ack = await this.api(`/commands/${run.command_id}:start`);
                    while (ack.status === 'pending') {
                        await new Promise(resolve => setTimeout(resolve, 150));
                        ack = await this.api(`/commands/${run.command_id}:start`);
                    }
                }
                catch (e) {
                    this.callbacks.onStartState(run.run_id, true, undefined, true);
                    throw e;
                }
                this.callbacks.onStartState(run.run_id, false, ack.generation);
                if (ack.status !== 'applied')
                    throw Error(ack.error || 'Run could not be started');
            }
        }
        else {
            const data = await this.api(`/config/${kind}`, config);
            this.setIssues([]);
            if (data.view) {
                this.setPreview(data.view);
                this.setArtifactId(data.artifact_id);
            }
            this.setResult(`Valid configuration · ${data.resolved.fingerprint.slice(0, 14)} · ${data.view ? 'Placement preview is independent of the live run.' : 'Configuration checks passed. Preview checks connectivity and generated placement before launch.'}`);
        }
    }
    catch (e: any) {
        if (handedOff)
            this.callbacks.onError(e.message);
        else
            this.reportDraftError(e);
    }
    finally {
        if (!handedOff) {
            this.busyRef.current = false;
            this.setBusy(false);
        }
    }
};
exportDraft = async () => {
    if (this.busyRef.current)
        return;
    let config: Obj;
    try {
        config = this.readDraft();
    }
    catch (error) {
        this.reportDraftError(error);
        return;
    }
    this.busyRef.current = true;
    this.setBusy(true);
    try {
        const data = await this.api('/config/export', { config, format: this.exportFormat });
        this.download(`scenario.${this.exportFormat}`, data.text);
        this.setResult('Configuration exported.');
        this.setIssues([]);
    }
    catch (error) {
        this.reportDraftError(error);
    }
    finally {
        this.busyRef.current = false;
        this.setBusy(false);
    }
};
importDraft = async (file?: File) => {
    if (!file || this.busyRef.current)
        return;
    try {
        this.requireReady();
    }
    catch (error) {
        this.reportDraftError(error);
        return;
    }
    this.busyRef.current = true;
    this.setBusy(true);
    try {
        const data = await this.api('/config/import', { text: await file.text(), format: file.name.endsWith('.toml') ? 'toml' : 'json' });
        const imported = parseConfigurationDraft(JSON.stringify(data.config) ?? '');
        readRoleGroups(imported, this.metadata!.presets);
        this.replaceDraft(imported);
    }
    catch (error) {
        this.reportDraftError(error);
    }
    finally {
        this.busyRef.current = false;
        this.setBusy(false);
    }
};
saveDraft = () => {
    if (this.busyRef.current)
        return;
    try {
        this.requireReady();
        if (Object.keys(this.numericTextRef.current).length || Object.keys(this.roleTextRef.current).length)
            this.readDraft();
        this.storage.setItem('zombie-draft', this.advancedRef.current);
        this.setResult('Draft saved in this workspace. Use Load saved draft to reopen it.');
    }
    catch (error) {
        this.reportDraftError(error);
    }
};
loadSavedDraft = () => {
    if (this.busyRef.current)
        return;
    try {
        this.requireReady();
        const saved = this.storage.getItem('zombie-draft');
        if (saved === null)
            throw Error('No saved draft is available in this browser workspace.');
        this.editAdvanced(saved);
        this.setModelEditorVersion(value => value + 1);
        try {
            this.setDraftValue(parseConfigurationDraft(saved));
            this.setResult('Saved draft loaded. Validate it before launching.');
        }
        catch (error) {
            this.reportDraftError(error);
        }
    }
    catch (error) {
        this.reportDraftError(error);
    }
};
discardAdvanced = () => { this.setAdvancedValue(JSON.stringify(this.draftRef.current, null, 2)); this.clearDraftFeedback(); };

}
