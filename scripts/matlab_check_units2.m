mdl = 'unit_probe2';
if bdIsLoaded(mdl); close_system(mdl,0); end
new_system(mdl);
src = add_block('ee_lib/Sources/Voltage Source (Three-Phase)', [mdl '/SRC']);
loadb = add_block('ee_lib/Passive/RLC Assemblies/Wye-Connected Load', [mdl '/LD']);
faultb = add_block('ee_lib/Utilities/Fault (Three-Phase)', [mdl '/F']);

fprintf('--- Source ---\n');
for p = {'vline_rms','freq','SShortCircuit','XR'}
    fprintf('%-14s value=%-12s unit=%s\n', p{1}, get_param(src,p{1}), get_param(src,[p{1} '_unit']));
end
fprintf('--- Load ---\n');
for p = {'VRated','FRated','P','Qpos'}
    fprintf('%-14s value=%-12s unit=%s\n', p{1}, get_param(loadb,p{1}), get_param(loadb,[p{1} '_unit']));
end
fprintf('--- Fault ---\n');
for p = {'R_pn_fault','R_ng_fault','fault_start_time','fault_duration','G_parasitic'}
    fprintf('%-14s value=%-12s unit=%s\n', p{1}, get_param(faultb,p{1}), get_param(faultb,[p{1} '_unit']));
end
close_system(mdl,0);
