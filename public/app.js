async function jget(u){const r=await fetch(u);return r.json()}
async function jpost(u,b={}){const r=await fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});return r.json()}
let OFFERS=[];
async function init(){
  const d=await jget('/api/offers');OFFERS=d.offers;
  document.getElementById('f-offer').innerHTML=OFFERS.map(o=>`<option value="${o.id}">${o.supplier} — ${o.name}</option>`).join('');
  document.getElementById('f-offer').value='edp-zero';
  load();
}
async function save(){
  const body={name:v('f-name'),email:v('f-email'),cpe:v('f-cpe'),current_supplier:v('f-supplier'),
    current_offer_id:v('f-offer'),power_kva:parseFloat(v('f-power')),tariff:v('f-tariff'),
    annual_kwh:parseFloat(v('f-kwh')),contract_end:v('f-end')||null,consent:document.getElementById('f-consent').checked,autoswitch:true};
  const r=await jpost('/api/contracts',body);
  document.getElementById('save-msg').textContent=r.ok?'saved id='+r.id:('ERR: '+(r.error||'?'));
  load();
}
function v(id){return document.getElementById(id).value}
async function load(){
  const c=await jget('/api/contracts');
  document.getElementById('contracts').innerHTML=c.contracts.length?c.contracts.map(x=>
    `<div>⚡ <b>#${x.id} ${x.name}</b> ${x.cpe} · ${x.current_supplier} · ${x.power_kva}kVA · ${x.annual_kwh}kWh · end ${x.contract_end||'—'}
    <button class="ghost" onclick="compare(${x.id})">Compare</button></div>`).join(''):'No contracts yet.';
  const s=await jget('/api/switches');
  document.getElementById('switches').innerHTML=s.switches.length?'<table><tr><th>ID</th><th>Contract</th><th>To</th><th>Saving €</th><th>Status</th><th></th></tr>'+
    s.switches.map(x=>`<tr><td>${x.id}</td><td>${x.contract_id}</td><td>${x.to_offer}</td><td>${x.saving_ex_vat}</td><td><span class="badge">${x.status}</span></td>
    <td>${x.status==='pending'?`<button class="ghost" onclick="act(${x.id},'confirm')">Confirm</button> <button class="ghost" onclick="act(${x.id},'cancel')">Cancel</button> <button onclick="act(${x.id},'execute')">Execute</button>`:''}</td></tr>`).join('')+'</table>':'No proposals. Run scan.';
  if(c.contracts.length) compare(c.contracts[0].id);
}
async function compare(id){
  const d=await jget('/api/compare?contract_id='+id);
  if(d.error){document.getElementById('compare').textContent=d.error;return;}
  let h=d.recommendation?`<p><span class="badge ok">SAVE ${d.recommendation.saving_ex_vat}€/yr ex-VAT → ${d.recommendation.offer.supplier} ${d.recommendation.offer.name}</span> ${d.due?'(contract due — eligible)':'(not due yet — will auto-switch at expiry)'}</p>`:'<p><span class="badge">No saving ≥20€ — stay.</span></p>';
  h+='<table><tr><th>Supplier</th><th>Offer</th><th>€/yr ex-VAT</th><th>€/yr inc VAT</th></tr>'+
    d.ranked.map(o=>`<tr><td>${o.supplier}</td><td>${o.name}</td><td>${o.est_annual_ex_vat}</td><td>${o.est_annual_inc_vat}</td></tr>`).join('')+'</table>';
  document.getElementById('compare').innerHTML=h;
}
async function runCron(){const r=await jpost('/api/cron/run',{min_saving:20});document.getElementById('cron-msg').textContent=r.ok?(' created '+r.created.length+' proposal(s)'):'ERR';load();}
async function act(id,a){await jpost('/api/switches/'+id+'/'+a,{});load();}
init();
