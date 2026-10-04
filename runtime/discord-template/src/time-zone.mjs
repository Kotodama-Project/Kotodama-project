// Config reloads and notification checks share formatters, including DST rules.
// Bound retained ICU objects when an operator changes the installation's zone.
const formatters=new Map(),maxFormatters=16;
function formatter(timeZone){
  if(typeof timeZone!=='string'||timeZone.length>100||!/^[A-Za-z][A-Za-z0-9._+-]*(?:\/[A-Za-z0-9._+-]+)*$/.test(timeZone))throw new RangeError('TIME_ZONE_INVALID');
  let value=formatters.get(timeZone);
  if(!value){
    value=new Intl.DateTimeFormat('en-GB',{timeZone,hour:'2-digit',hourCycle:'h23'});
    if(formatters.size>=maxFormatters)formatters.delete(formatters.keys().next().value);
    formatters.set(timeZone,value);
  }
  return value;
}
export function isTimeZone(timeZone){try{formatter(timeZone);return true;}catch{return false;}}
export function hourInTimeZone(timeZone,date){return Number(formatter(timeZone).format(date));}
