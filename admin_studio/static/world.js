"use strict";
const worldApi=(path,data)=>api(path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(data)});
let activeCity="ufa", selectedKind="school", buildings=[], originX=0,originY=0;
const canvas=document.getElementById("worldmap"), ctx=canvas.getContext("2d");
function drawWorld(){
  ctx.clearRect(0,0,canvas.width,canvas.height);
  ctx.fillStyle="#183c2b";ctx.fillRect(0,0,canvas.width,canvas.height);
  const cell=24;
  for(let x=0;x<canvas.width/cell;x++)for(let y=0;y<canvas.height/cell;y++){
    ctx.strokeStyle="#35654b";ctx.strokeRect(x*cell,y*cell,cell,cell);
  }
  const dims={school:[3,2],hospital:[3,3],park:[2,2]};
  buildings.forEach(b=>{
    const d=dims[b.kind]||[1,1];
    ctx.fillStyle=b.kind==="park"?"#5da96a":b.kind==="hospital"?"#82a7d4":"#d9b17c";
    ctx.fillRect((b.x-originX)*cell+1,(b.y-originY)*cell+1,d[0]*cell-2,d[1]*cell-2);
    ctx.fillStyle="#0b2317";ctx.font="12px system-ui";ctx.fillText(b.kind,(b.x-originX)*cell+4,(b.y-originY)*cell+17);
  });
}
async function reloadWorld(){
  const data=await api("/api/cities/"+encodeURIComponent(activeCity));
  buildings=data.buildings;
  document.getElementById("cityinfo").textContent=data.title+" · объектов: "+buildings.length;
  drawWorld();
}
document.getElementById("citysave").onsubmit=async e=>{
  e.preventDefault();
  try{
    const f=new FormData(e.target);
    const settings={population:Number(f.get("population")),profit_tax:Number(f.get("profit_tax")),
      property_tax:Number(f.get("property_tax")),month_seconds:Number(f.get("month_seconds")),
      growth_per_month:Number(f.get("growth_per_month"))};
    activeCity=f.get("id");
    await worldApi("/api/cities",{id:activeCity,title:f.get("title"),settings});
    await reloadWorld();
    document.getElementById("citymessage").textContent="Черновик сохранён";
  }catch(err){document.getElementById("citymessage").textContent="Ошибка: "+err.message}
};
document.getElementById("buildingkind").onchange=e=>selectedKind=e.target.value;
canvas.addEventListener("click",async e=>{
  const rect=canvas.getBoundingClientRect(),x=originX+Math.floor((e.clientX-rect.left)*canvas.width/rect.width/24),
    y=originY+Math.floor((e.clientY-rect.top)*canvas.height/rect.height/24);
  try{
    await worldApi("/api/buildings",{city_id:activeCity,kind:selectedKind,x,y});
    await reloadWorld();document.getElementById("citymessage").textContent="Здание добавлено в черновик";
  }catch(err){document.getElementById("citymessage").textContent="Ошибка: "+err.message}
});
document.getElementById("forecast").onclick=async()=>{
  try{const d=await worldApi("/api/forecast",{city_id:activeCity,months:12});
    document.getElementById("forecastresult").textContent="Примерный прогноз населения через 12 месяцев: "+d.final_population+" (без моделирования экономики)";}
  catch(err){document.getElementById("forecastresult").textContent=err.message}
};
document.getElementById("exportcity").onclick=async()=>{
  try{const data=await worldApi("/api/export-city",{city_id:activeCity});
    const blob=new Blob([JSON.stringify(data,null,2)],{type:"application/json"});
    const url=URL.createObjectURL(blob),a=document.createElement("a");a.href=url;a.download="city-"+activeCity+"-draft.json";a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  catch(err){document.getElementById("citymessage").textContent=err.message}
};
document.getElementById("panleft").onclick=()=>{originX-=5;drawWorld()};
document.getElementById("panright").onclick=()=>{originX+=5;drawWorld()};
document.getElementById("panup").onclick=()=>{originY-=5;drawWorld()};
document.getElementById("pandown").onclick=()=>{originY+=5;drawWorld()};
drawWorld();
