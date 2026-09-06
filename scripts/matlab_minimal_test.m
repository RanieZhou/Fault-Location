% 最小可跑通模型测试: 电源 -> 线路 -> 负荷, 外加故障模块和测量模块。
% 目的:在写批量建模脚本之前,先确认每个模块的准确库路径、必需的辅助模块
% (Solver Configuration / Electrical Reference)、端口连接方式都是对的。
mdl = 'mini_test';
if bdIsLoaded(mdl)
    close_system(mdl, 0);
end
new_system(mdl);
open_system(mdl);

candidates = struct( ...
    'src', {{'ee_lib/Sources/Voltage Source (Three-Phase)'}}, ...
    'line', {{'ee_lib/Passive/Lines/Transmission Line (Three-Phase)'}}, ...
    'load', {{'ee_lib/Passive/RLC Assemblies/Wye-Connected Load'}}, ...
    'fault', {{'ee_lib/Utilities/Fault (Three-Phase)'}}, ...
    'solver', {{'nesl_utility/Solver Configuration'}}, ...
    'eref', {{'ee_lib/Connectors & References/Electrical Reference'}}, ...
    'gndneutral', {{'ee_lib/Connectors & References/Grounded Neutral (Three-Phase)'}}, ...
    'vsensor', {{'ee_lib/Sensors & Transducers/Line Voltage Sensor (Three-Phase)'}}, ...
    'isensor', {{'ee_lib/Sensors & Transducers/Current Sensor (Three-Phase)', ...
                  'ee_lib/Sensors & Transducers/Line Current Sensor (Three-Phase)', ...
                  'ee_lib/Sensors & Transducers/Ammeter'}} ...
);

fns = fieldnames(candidates);
resolved = struct();
for i = 1:numel(fns)
    fn = fns{i};
    opts = candidates.(fn);
    ok = false;
    for j = 1:numel(opts)
        p = opts{j};
        try
            testname = [mdl '/probe_' fn];
            add_block(p, testname);
            fprintf('OK   %-10s -> %s\n', fn, p);
            resolved.(fn) = p;
            ok = true;
            break;
        catch ME
            fprintf('FAIL %-10s -> %s  (%s)\n', fn, p, ME.message);
        end
    end
    if ~ok
        fprintf('*** 全部候选都失败: %s ***\n', fn);
    end
end

fprintf('\n=== 已解析的模块路径 ===\n');
disp(resolved);

save('resolved_blocks.mat', 'resolved');
fprintf('已保存 resolved_blocks.mat\n');
close_system(mdl, 0);
