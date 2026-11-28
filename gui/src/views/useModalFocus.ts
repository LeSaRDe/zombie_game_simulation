import React,{useEffect} from 'react';
export function useModalFocus(ref:React.RefObject<HTMLElement|null>,onClose:()=>void){
  useEffect(()=>{const previous=document.activeElement as HTMLElement|null;const controls=()=>Array.from(ref.current?.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),summary,a[href]')||[]).filter(el=>el.offsetParent!==null);controls()[0]?.focus();const handle=(event:KeyboardEvent)=>{if(event.key==='Escape'){event.preventDefault();onClose();}if(event.key==='Tab'){const items=controls();const first=items[0],last=items.at(-1);if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}}};document.addEventListener('keydown',handle);return()=>{document.removeEventListener('keydown',handle);if(previous?.isConnected)previous.focus();};},[]);
}

