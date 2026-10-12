import {defaultDate, defaultOwner, queryUrl} from './client.js';

// Opening a workspace carries a private draft, never starts model work.
export async function openAssistant({focus=defaultOwner(),as_of=defaultDate(),mode='current',question=''}={}){
  const context={focus,as_of,mode};
  try{
    if(question.trim()){
      const response=await fetch('/network/strategy/drafts',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question})});
      const data=await response.json();if(!response.ok)throw new Error(data.error||'Could not carry your question into Strategy.');
      context.draft=data.draft_id;
    }
    location.assign(queryUrl('/strategy',context));
  }catch{
    let notice=document.getElementById('strategy-handoff-error');
    if(!notice){notice=document.createElement('p');notice.id='strategy-handoff-error';notice.setAttribute('role','alert');(document.querySelector('.discovery-output')||document.querySelector('main')||document.body).prepend(notice);}
    notice.textContent='Could not open Strategy. Your question has been kept; try again when the local app is available.';
  }
}
