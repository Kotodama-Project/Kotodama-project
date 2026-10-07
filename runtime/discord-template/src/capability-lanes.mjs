// Descriptive mapping of the existing action vocabulary. worker.actions remains
// the only runtime grant; a lane or risk label never authorizes execution.
export const ACTION_LANES=Object.freeze({
  research:Object.freeze({lane:'inspect',riskClass:'inspect',defaultGranted:true}),
  summarize:Object.freeze({lane:'inspect',riskClass:'inspect',defaultGranted:true}),
  write_file:Object.freeze({lane:'edit',riskClass:'reversible_change',defaultGranted:false}),
  develop:Object.freeze({lane:'edit',riskClass:'reversible_change',defaultGranted:false}),
  create_company_pack:Object.freeze({lane:'edit',riskClass:'reversible_change',defaultGranted:false,manualOnly:true}),
  swarm_research:Object.freeze({lane:'inspect',riskClass:'inspect',defaultGranted:false,manualOnly:true})
});
export const WORKER_ACTIONS=Object.freeze(Object.keys(ACTION_LANES));
export const DEFAULT_WORKER_ACTIONS=Object.freeze(WORKER_ACTIONS.filter(action=>ACTION_LANES[action].defaultGranted));
export const INTENT_ACTIONS=Object.freeze(['none',...WORKER_ACTIONS.filter(action=>!ACTION_LANES[action].manualOnly)]);
