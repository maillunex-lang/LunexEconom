const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const context={window:{}};
vm.runInNewContext(fs.readFileSync(__dirname+'/../help.js','utf8'),context);
const help=context.window.ADMIN_HELP;
for(const name of ['overview','players','economy','cities','events','server','alerts','settings','catalog','announcements','releases','audit']){
  assert.match(help.section(name),/Рекомендации/);
  assert.match(help.section(name),/Ограничения/);
}
for(const key of ['registration_enabled','world_growth_threshold_bp','retail_vat_bp_draft','logistics_fuel_required','build_materials_required']){
  assert.match(help.setting(key,1,0,[0,10000]),/Значение по умолчанию/);
}
assert.match(help.setting('<script>',0,0,null),/&lt;script&gt;/);
assert.doesNotMatch(help.setting('<script>',0,0,null),/<script>/);
assert.match(help.setting('unknown',0,0,null),/не подтверждено/);
console.log('Admin help tests passed');
