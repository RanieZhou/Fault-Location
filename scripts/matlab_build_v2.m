mdl = 'mini_v2';
if bdIsLoaded(mdl)
    close_system(mdl, 0);
end
new_system(mdl);
open_system(mdl);

src    = add_block('ee_lib/Sources/Voltage Source (Three-Phase)', [mdl '/Source']);
line   = add_block('ee_lib/Passive/Lines/Transmission Line (Three-Phase)', [mdl '/Line']);
isense = add_block('ee_lib/Sensors & Transducers/Current Sensor (Three-Phase)', [mdl '/Isense']);
loadb  = add_block('ee_lib/Passive/RLC Assemblies/Wye-Connected Load', [mdl '/Load']);
faultb = add_block('ee_lib/Utilities/Fault (Three-Phase)', [mdl '/Fault']);
solver = add_block('nesl_utility/Solver Configuration', [mdl '/SolverCfg']);
eref   = add_block('ee_lib/Connectors & References/Electrical Reference', [mdl '/Eref']);

set_param(line, 'Access_ground', 'off');
set_param(src, 'vline_rms', '10e3');
set_param(src, 'freq', '50');
set_param(line, 'length', '1');
set_param(loadb, 'VRated', '10e3/sqrt(3)');

try_pair(mdl, 'Eref-Source.L',   P(mdl,'Eref').LConn(1), P(mdl,'Source').LConn(1));
try_pair(mdl, 'Source.R-Line.L', P(mdl,'Source').RConn(1), P(mdl,'Line').LConn(1));
try_pair(mdl, 'Line.R-Isense.L', P(mdl,'Line').RConn(1), P(mdl,'Isense').LConn(1));
try_pair(mdl, 'Isense.R2-Load.L', P(mdl,'Isense').RConn(2), P(mdl,'Load').LConn(1));
try_pair(mdl, 'Load.R-Eref(branch)', P(mdl,'Load').RConn(1), P(mdl,'Eref').LConn(1));
try_pair(mdl, 'Fault.L-Load.L(branch to same node)', P(mdl,'Fault').LConn(1), P(mdl,'Load').LConn(1));
try_pair(mdl, 'SolverCfg-Eref(branch)', P(mdl,'SolverCfg').RConn(1), P(mdl,'Eref').LConn(1));

save_system(mdl, fullfile(pwd, [mdl '.slx']));

fprintf('\n=== 编译测试 ===\n');
try
    set_param(mdl, 'SimulationCommand', 'update');
    fprintf('编译成功!\n');
catch ME
    fprintf('编译失败: %s\n', ME.message);
end

fprintf('\n=== 跑个1秒仿真, 开Simscape自动记录, 看看能不能不接传感器直接读电压电流 ===\n');
try
    set_param(mdl, 'StopTime', '0.1');
    simOut = sim(mdl, 'ReturnWorkspaceOutputs', 'on', 'SimscapeLogType', 'all');
    logname = ['simlog_' mdl];
    if isprop(simOut, logname) || isfield(simOut, logname)
        slog = simOut.get(logname);
        fprintf('拿到了 simscape log, 顶层子项:\n');
        disp(slog.children);
    else
        fprintf('simOut 里没找到 %s, simOut 的属性有:\n', logname);
        disp(simOut.who);
    end
catch ME2
    fprintf('仿真失败: %s\n', ME2.message);
end

close_system(mdl, 1);

function ph = P(mdl, name)
    ph = get_param([mdl '/' name], 'PortHandles');
end
function ok = try_pair(mdl, label, p1, p2)
    try
        add_line(mdl, p1, p2, 'autorouting', 'on');
        fprintf('OK   %s\n', label);
        ok = true;
    catch ME
        fprintf('FAIL %s : %s\n', label, ME.message(1:min(80,end)));
        ok = false;
    end
end
