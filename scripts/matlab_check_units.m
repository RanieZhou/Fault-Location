mdl = 'unit_probe';
if bdIsLoaded(mdl); close_system(mdl,0); end
new_system(mdl);
lineblk = add_block('ee_lib/Passive/Lines/Transmission Line (Three-Phase)', [mdl '/L']);
for p = {'R','L','M','Cl','Cg','Rm','length'}
    fprintf('%-8s value=%-12s unit=%s\n', p{1}, get_param(lineblk,p{1}), get_param(lineblk,[p{1} '_unit']));
end
close_system(mdl,0);
