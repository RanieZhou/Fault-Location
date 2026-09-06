mdl = 'mini_v2';
open_system(fullfile(pwd, [mdl '.slx']));
faultblk = [mdl '/Fault'];
loadblk = [mdl '/Load'];

fprintf('class(fault_type_option) = %s\n', class(get_param(faultblk,'fault_type_option')));
fprintf('class(enable_temporal_fault) = %s\n', class(get_param(faultblk,'enable_temporal_fault')));
fprintf('class(fault_resettable) = %s\n', class(get_param(faultblk,'fault_resettable')));

enumnames = {'ee.enum.rlc.parameterization','ee.enum.rlc.structure'};
for i=1:numel(enumnames)
    try
        vals = enumeration(enumnames{i});
        fprintf('\n=== enumeration(%s) ===\n', enumnames{i});
        for v = 1:numel(vals)
            fprintf('  %s\n', char(vals(v)));
        end
    catch ME
        fprintf('%s 枚举失败: %s\n', enumnames{i}, ME.message);
    end
end

% fault_type_option 和 enable_temporal_fault 的类型未知,先反查它们的mask源属性类型
mo = get_param(faultblk, 'MaskObject');
p = mo.getParameter('fault_type_option');
fprintf('\nfault_type_option Type=%s\n', p.Type);
if isprop(p, 'TypeOptions')
    disp(p.TypeOptions);
end
p2 = mo.getParameter('enable_temporal_fault');
fprintf('enable_temporal_fault Type=%s\n', p2.Type);
if isprop(p2, 'TypeOptions')
    disp(p2.TypeOptions);
end

close_system(mdl, 0);
