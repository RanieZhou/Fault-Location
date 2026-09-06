mdl = 'mini_v2';
open_system(fullfile(pwd, [mdl '.slx']));

srcblk = [mdl '/Source'];
loadblk = [mdl '/Load'];
faultblk = [mdl '/Fault'];
solverblk = [mdl '/SolverCfg'];

fprintf('=== SolverCfg 可设参数 ===\n');
dp = get_param(solverblk, 'DialogParameters');
disp(fieldnames(dp));

% 用固定步长本地求解器,规避故障投切瞬间的刚性问题
set_param(solverblk, 'UseLocalSolver', 'on');
set_param(solverblk, 'LocalSolverChoice', 'NE_BACKWARD_EULER_ADVANCER');
set_param(solverblk, 'LocalSolverSampleTime', '2e-5');

set_param(loadblk, 'component_structure_PQ', 'ee.enum.rlc.structure.ParallelRLC');
set_param(loadblk, 'VRated', '5.77e3');
set_param(loadblk, 'FRated', '50');
set_param(loadblk, 'P', '100e3');
set_param(loadblk, 'Qpos', '30e3');

set_param(faultblk, 'fault_start_time', '0.03');
set_param(faultblk, 'fault_duration', '0.02');
set_param(faultblk, 'R_pn_fault', '5');
set_param(faultblk, 'R_ng_fault', '5');
set_param(mdl, 'StopTime', '0.08');

fprintf('\n=== 基线(无故障), 测 Source.I ===\n');
set_param(faultblk, 'enable_temporal_fault', '0');
simOut0 = sim(mdl, 'ReturnWorkspaceOutputs', 'on', 'SimscapeLogType', 'all');
slog0 = simOut0.simlog;
t0 = slog0.Source.I.series.time;
I0 = slog0.Source.I.series.values;
idx0 = t0 > 0.02 & t0 < 0.03;
Irms0 = sqrt(mean(I0(idx0,:).^2,1));
fprintf('基线 Source Irms(3相) = %s\n', mat2str(round(Irms0,2)));

set_param(faultblk, 'enable_temporal_fault', '1');
fprintf('\n=== 固定步长求解器 + 测Source.I, 遍历 fault_type_option 0~11 ===\n');
for k = 0:11
    set_param(faultblk, 'fault_type_option', num2str(k));
    try
        simOut = sim(mdl, 'ReturnWorkspaceOutputs', 'on', 'SimscapeLogType', 'all');
        slog = simOut.simlog;
        t = slog.Source.I.series.time;
        I = slog.Source.I.series.values;
        idx_fault = t > 0.045 & t < 0.049;
        Irms_fault = sqrt(mean(I(idx_fault,:).^2,1));
        ratio = Irms_fault ./ max(Irms0, 1e-6);
        fprintf('type=%2d  Irms_fault=%-30s ratio=%-30s\n', k, mat2str(round(Irms_fault,1)), mat2str(round(ratio,2)));
    catch ME
        fprintf('type=%2d  仿真出错: %s\n', k, ME.message(1:min(50,end)));
    end
end

close_system(mdl, 0);
