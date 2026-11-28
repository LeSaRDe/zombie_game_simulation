import {Obj,Bundle,ViewerLoad,inspection} from '../uiRuntime';
import {RequestTransport} from './contracts';
import {isInactiveRun} from '../runLifecycle';
type Ref<T>={current:T};
export interface ViewSessionOptions {runIdRef:Ref<string>;perspectiveRef:Ref<string>;liveRef:Ref<'live'|'replay'>;viewRef:Ref<Bundle|undefined>;viewerLoadRef:Ref<ViewerLoad>;runRef:Ref<Obj|undefined>;setView(value:Bundle|undefined):void;setSeek(value:string):void;setViewerState(value:ViewerLoad):void;setViewPending(value:boolean):void;setError(value:string):void}
/** Owns generation-cancelled history reads and the current live socket. */
export class ViewSession {
 readonly requestGeneration={current:0};readonly viewAbort:Ref<AbortController|undefined>={current:undefined};readonly streamRef:Ref<WebSocket|undefined>={current:undefined};readonly lastViewRequest:Ref<{time?:string;revision?:string}>={current:{}};
 private releaseStream?:()=>void;
 constructor(public options:ViewSessionOptions,private readonly api:RequestTransport){}
 cancel=()=>{this.viewAbort.current?.abort();this.viewAbort.current=undefined;this.requestGeneration.current++;this.streamRef.current?.close();this.streamRef.current=undefined;};
 dispose=()=>{this.releaseStream?.();this.cancel();};
 acceptView = (data: Bundle, identity: string) => {
    if (this.options.runIdRef.current !== identity || data.run_id !== identity || this.options.perspectiveRef.current !== 'researcher')
        return;
    const old = this.options.viewRef.current;
    if (this.options.liveRef.current === 'live' && old?.run_id === identity && old.mode === 'live' && BigInt(data.revision) < BigInt(old.revision))
        return;
    inspection.transport.application_trace.push({ run_id: identity, revision: data.revision, mode: this.options.liveRef.current, at: performance.now() });
    this.options.viewRef.current = data;
    this.options.setView(data);
    this.options.setSeek(data.time);
    this.options.setViewerState({ phase: 'ready', run_id: identity });
};
loadView = async (time?: string, revision?: string) => {
    const identity = this.options.runIdRef.current;
    if (!identity || this.options.perspectiveRef.current !== 'researcher')
        return;
    this.viewAbort.current?.abort();
    const controller = new AbortController();
    this.viewAbort.current = controller;
    const token = ++this.requestGeneration.current;
    this.lastViewRequest.current = { time, revision };
    this.options.setViewPending(true);
    this.options.setViewerState({ phase: 'loading', run_id: identity });
    try {
        const query = new URLSearchParams({ generation: String(token) });
        if (time !== undefined)
            query.set('time', time);
        if (revision !== undefined)
            query.set('revision', revision);
        const data = await this.api(`/runs/${identity}/view?${query}`, undefined, controller.signal);
        if (!data || data.run_id !== identity || !data.state?.world || !data.state?.agents || !data.metrics?.populations || data.revision === undefined || data.time === undefined) {
            throw Error('The service returned an incomplete history view. Retry loading or return to the run list.');
        }
        if (!controller.signal.aborted && token === this.requestGeneration.current && identity === this.options.runIdRef.current && this.options.perspectiveRef.current === 'researcher') {
            this.acceptView(data, identity);
            return data;
        }
    }
    catch (e: any) {
        if (!controller.signal.aborted && token === this.requestGeneration.current && identity === this.options.runIdRef.current) {
            const currentRun = this.options.runRef.current;
            if (e.code === 'RUN_INITIALIZING' && currentRun?.status === 'initializing')
                this.options.setViewerState({ phase: 'initializing', run_id: identity });
            else if (e.code === 'RUN_INITIALIZING' && !currentRun)
                this.options.setViewerState({ phase: 'loading', run_id: identity, details: true });
            else
                this.options.setViewerState({ phase: 'failed', run_id: identity, error: e.code === 'RUN_INITIALIZING' ? `Recorded history is unavailable for this ${currentRun?.status} run (${e.code}). Retry loading or return to the run list.` : e.message });
        }
    }
    finally {
        if (token === this.requestGeneration.current && identity === this.options.runIdRef.current) {
            this.options.setViewPending(false);
            if (this.viewAbort.current === controller)
                this.viewAbort.current = undefined;
        }
    }
};

 follow=(runId:string,terminalCursor:string)=>{let disposed = false;
let terminalPacket = false;
let socket: WebSocket | undefined;
let ownedController: AbortController | undefined;
let retry: ReturnType<typeof setTimeout>;
const current = this.options.viewRef.current;
if (terminalCursor && current?.run_id === runId && current.mode === 'live' && String(current.revision) === String(this.options.runRef.current?.frontier?.revision)) {
    // Cleanup may have invalidated an in-flight refresh's generation. Its
    // finally block then cannot clear pending; this verified reused view can.
    this.options.setViewPending(false);
    this.options.setViewerState({ phase: 'ready', run_id: runId });
    return;
}
const connect = async () => {
    if (disposed || this.options.runIdRef.current !== runId)
        return;
    const loading = this.loadView();
    ownedController = this.viewAbort.current;
    const first = await loading;
    if (disposed || this.options.runIdRef.current !== runId)
        return;
    if (!first) {
        // Only genuine, service-confirmed initialization is retried without a
        // click. A loading failure has its own error and explicit retry path.
        if (this.options.viewerLoadRef.current.phase === 'initializing')
            retry = setTimeout(connect, 1000);
        return;
    }
    if (isInactiveRun(first.control) || isInactiveRun(this.options.runRef.current))
        return;
    socket = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/runs/${runId}/stream`);
    this.streamRef.current = socket;
    socket.onmessage = event => {
        if (disposed || this.streamRef.current !== socket || this.options.runIdRef.current !== runId || this.options.liveRef.current !== 'live' || this.options.perspectiveRef.current !== 'researcher')
            return;
        try {
            inspection.transport.queue_depth++;
            inspection.transport.max_queue_depth = Math.max(inspection.transport.max_queue_depth, inspection.transport.queue_depth);
            const data = JSON.parse(event.data);
            if (!disposed && this.streamRef.current === socket && this.options.runIdRef.current === runId && this.options.liveRef.current === 'live' && this.options.perspectiveRef.current === 'researcher')
                this.acceptView(data, runId);
            terminalPacket = isInactiveRun(data.control);
            socket?.send(JSON.stringify({ ack: data.sequence }));
        }
        catch (e: any) {
            if (!disposed)
                this.options.setError(`Live update could not be read: ${e.message}`);
        }
        finally {
            inspection.transport.queue_depth = Math.max(0, inspection.transport.queue_depth - 1);
        }
    };
    socket.onclose = () => { if (!disposed && this.streamRef.current === socket && !terminalPacket && this.options.runIdRef.current === runId && this.options.liveRef.current === 'live' && this.options.perspectiveRef.current === 'researcher' && !isInactiveRun(this.options.runRef.current))
        retry = setTimeout(connect, 1000); };
};
connect();
const release = () => {
    disposed = true;
    clearTimeout(retry);
    ownedController?.abort();
    if (ownedController && this.viewAbort.current === ownedController) {
        this.viewAbort.current = undefined;
        this.requestGeneration.current++;
    }
    socket?.close();
    if (this.streamRef.current === socket)
        this.streamRef.current = undefined;
};
this.releaseStream = release;
return release;
};
}
