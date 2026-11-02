// A completed external job is authoritative only when current is its verified result.
export function completedExternalToken(current,job,pending){
 if(pending||job?.status!=='completed'||typeof job.token!=='string'||!job.token||current?.settings?.token!==job.token)return null;
 return job.token;
}

// Only erase the exact job error we previously displayed, never unrelated UI messages.
export function staleJobError(displayed,currentMessage,job){
 return !!displayed&&!job?.error&&currentMessage===displayed;
}

// A texture upload can change only the complete asset revision.
export function catalogSignature(assets){
 return assets.filter(a=>a.enabled).map(a=>[a.asset_id,a.render_revision,a.material_revision,a.asset_revision].join(':')).join();
}
