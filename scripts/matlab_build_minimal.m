mdl = 'mini_circuit';
if bdIsLoaded(mdl)
    close_system(mdl, 0);
end
new_system(mdl);
open_system(mdl);

% 先看一下 Source 自己的可配参数,搞清楚中性点怎么处理
tmp = add_block('ee_lib/Sources/Voltage Source (Three-Phase)', [mdl '/tmp_src']);
dp = get_param(tmp, 'DialogParameters');
fprintf('=== Voltage Source(Three-Phase) 参数 ===\n');
disp(fieldnames(dp));
md = get_param(tmp, 'MaskDisplay');
fprintf('--- Source MaskDisplay(找port_label)---\n%s\n', md);
delete_block(tmp);

for probe_name = {'ee_lib/Passive/Lines/Transmission Line (Three-Phase)', ...
                   'ee_lib/Sensors & Transducers/Current Sensor (Three-Phase)', ...
                   'ee_lib/Passive/RLC Assemblies/Wye-Connected Load'}
    t2 = add_block(probe_name{1}, [mdl '/tmp_probe']);
    md2 = get_param(t2, 'MaskDisplay');
    fprintf('--- %s MaskDisplay ---\n%s\n', probe_name{1}, md2);
    delete_block(t2);
end

% ---- 搭最小电路: Source -> Line -> Load, Fault接在Load端母线, 加电压/电流传感器 ----
src = add_block('ee_lib/Sources/Voltage Source (Three-Phase)', [mdl '/Source']);
set_param(src, 'Position', [50 50 100 100]);

line = add_block('ee_lib/Passive/Lines/Transmission Line (Three-Phase)', [mdl '/Line']);
set_param(line, 'Position', [200 50 260 100]);
set_param(line, 'Access_ground', 'off');

load = add_block('ee_lib/Passive/RLC Assemblies/Wye-Connected Load', [mdl '/Load']);
set_param(load, 'Position', [400 50 450 100]);

fault = add_block('ee_lib/Utilities/Fault (Three-Phase)', [mdl '/Fault']);
set_param(fault, 'Position', [400 200 450 250]);

solver = add_block('nesl_utility/Solver Configuration', [mdl '/SolverCfg']);
set_param(solver, 'Position', [50 200 100 250]);

eref = add_block('ee_lib/Connectors & References/Electrical Reference', [mdl '/Gnd1']);
set_param(eref, 'Position', [50 300 100 350]);

eref2 = add_block('ee_lib/Connectors & References/Electrical Reference', [mdl '/Gnd2']);
set_param(eref2, 'Position', [500 300 550 350]);

gndneutral = add_block('ee_lib/Connectors & References/Grounded Neutral (Three-Phase)', [mdl '/SrcNeutral']);
set_param(gndneutral, 'Position', [50 100 100 150]);

vsensor = add_block('ee_lib/Sensors & Transducers/Line Voltage Sensor (Three-Phase)', [mdl '/Vsense']);
set_param(vsensor, 'Position', [300 300 350 350]);

isensor = add_block('ee_lib/Sensors & Transducers/Current Sensor (Three-Phase)', [mdl '/Isense']);
set_param(isensor, 'Position', [320 50 370 100]);

steps = {
    {'SrcNeutral-Source', @() add_line(mdl, P(mdl,'SrcNeutral').LConn(1), P(mdl,'Source').LConn(1))}
    {'Source-Line',       @() add_line(mdl, P(mdl,'Source').RConn(1), P(mdl,'Line').LConn(1))}
    {'Line-Isense',       @() add_line(mdl, P(mdl,'Line').RConn(1), P(mdl,'Isense').LConn(1))}
    {'Isense-Load',       @() add_line(mdl, P(mdl,'Isense').RConn(1), P(mdl,'Load').LConn(1))}
    {'Load-Gnd2',         @() add_line(mdl, P(mdl,'Load').RConn(1), P(mdl,'Gnd2').LConn(1))}
    {'Isense-Fault',      @() add_line(mdl, P(mdl,'Isense').RConn(1), P(mdl,'Fault').LConn(1))}
    {'Isense-Vsense',     @() add_line(mdl, P(mdl,'Isense').RConn(1), P(mdl,'Vsense').LConn(1))}
    {'Gnd2-Vsense',       @() add_line(mdl, P(mdl,'Gnd2').LConn(1), P(mdl,'Vsense').RConn(1))}
    {'SolverCfg-Gnd1',    @() add_line(mdl, P(mdl,'SolverCfg').RConn(1), P(mdl,'Gnd1').LConn(1))}
};
for si = 1:numel(steps)
    label = steps{si}{1};
    fn = steps{si}{2};
    try
        fn();
        fprintf('OK   %s\n', label);
    catch ME
        fprintf('FAIL %s : %s\n', label, ME.message);
    end
end

save_system(mdl, fullfile(pwd, [mdl '.slx']));
fprintf('已保存 %s.slx\n', mdl);

fprintf('\n=== 尝试编译模型(update diagram) ===\n');
try
    set_param(mdl, 'SimulationCommand', 'update');
    fprintf('编译成功!\n');
catch ME2
    fprintf('编译失败: %s\n', ME2.message);
end

close_system(mdl, 1);

function ph = P(mdl, name)
    ph = get_param([mdl '/' name], 'PortHandles');
end
