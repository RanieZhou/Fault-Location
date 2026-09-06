mdl = 'port_probe';
if bdIsLoaded(mdl)
    close_system(mdl, 0);
end
new_system(mdl);

blocks = struct( ...
    'src', 'ee_lib/Sources/Voltage Source (Three-Phase)', ...
    'line', 'ee_lib/Passive/Lines/Transmission Line (Three-Phase)', ...
    'load', 'ee_lib/Passive/RLC Assemblies/Wye-Connected Load', ...
    'fault', 'ee_lib/Utilities/Fault (Three-Phase)', ...
    'solver', 'nesl_utility/Solver Configuration', ...
    'eref', 'ee_lib/Connectors & References/Electrical Reference', ...
    'gndneutral', 'ee_lib/Connectors & References/Grounded Neutral (Three-Phase)', ...
    'vsensor', 'ee_lib/Sensors & Transducers/Line Voltage Sensor (Three-Phase)', ...
    'isensor', 'ee_lib/Sensors & Transducers/Current Sensor (Three-Phase)' ...
);

fns = fieldnames(blocks);
for i = 1:numel(fns)
    fn = fns{i};
    blk = add_block(blocks.(fn), [mdl '/' fn]);
    ph = get_param(blk, 'PortHandles');
    fprintf('\n--- %s (%s) ---\n', fn, blocks.(fn));
    disp(ph);
    pc = get_param(blk, 'PortConnectivity');
    for k = 1:numel(pc)
        fprintf('  port %d: Type=%s\n', k, pc(k).Type);
    end
end

% 额外看一下 fault 模块的参数(想知道怎么设相别/电阻/起止时间)
fprintf('\n=== Fault(Three-Phase) 可设参数 ===\n');
fblk = [mdl '/fault'];
dp = get_param(fblk, 'DialogParameters');
disp(fieldnames(dp));

fprintf('\n=== Wye-Connected Load 可设参数 ===\n');
lblk = [mdl '/load'];
dp2 = get_param(lblk, 'DialogParameters');
disp(fieldnames(dp2));

fprintf('\n=== Transmission Line (Three-Phase) 可设参数 ===\n');
tblk = [mdl '/line'];
dp3 = get_param(tblk, 'DialogParameters');
disp(fieldnames(dp3));

close_system(mdl, 0);
