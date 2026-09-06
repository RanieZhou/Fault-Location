mdl = 'mini_v2';
open_system(fullfile(pwd, [mdl '.slx']));

srcblk = [mdl '/Source'];
loadblk = [mdl '/Load'];
faultblk = [mdl '/Fault'];

set_param(loadblk, 'component_structure_PQ', 'ee.enum.rlc.structure.ParallelRLC');
set_param(loadblk, 'VRated', '5.77e3');
set_param(loadblk, 'FRated', '50');
set_param(loadblk, 'P', '100e3');
set_param(loadblk, 'Qpos', '30e3');

set_param(faultblk, 'enable_temporal_fault', '1');
set_param(faultblk, 'fault_start_time', '0.03');
set_param(faultblk, 'fault_duration', '0.02');
set_param(faultblk, 'R_pn_fault', '1');
set_param(faultblk, 'R_ng_fault', '1');

set_param(mdl, 'StopTime', '0.08');

fprintf('=== 先跑一次无故障基线,核对电压电流量级是否符合物理预期 ===\n');
set_param(faultblk, 'enable_temporal_fault', '0');
simOut0 = sim(mdl, 'ReturnWorkspaceOutputs', 'on', 'SimscapeLogType', 'all');
slog0 = simOut0.simlog;
t0 = slog0.Load.wye_impedance.V.series.time;
V0 = slog0.Load.wye_impedance.V.series.values;
I0 = slog0.Load.wye_impedance.I.series.values;
idx0 = t0 > 0.02;
Vrms0 = sqrt(mean(V0(idx0,:).^2,1));
Irms0 = sqrt(mean(I0(idx0,:).^2,1));
fprintf('基线 Vrms(3相)=%s (期望约5770V)\n', mat2str(round(Vrms0)));
fprintf('基线 Irms(3相)=%s (期望约 100e3/3/5770*某系数, 量级几A到十几A)\n', mat2str(round(Irms0,2)));

set_param(faultblk, 'enable_temporal_fault', '1');
fprintf('\n=== 遍历 fault_type_option 0~11, 看哪个组合对应哪几相电流升高 ===\n');
for k = 0:11
    set_param(faultblk, 'fault_type_option', num2str(k));
    try
        simOut = sim(mdl, 'ReturnWorkspaceOutputs', 'on', 'SimscapeLogType', 'all');
        slog = simOut.simlog;
        t = slog.Load.wye_impedance.I.series.time;
        I = slog.Load.wye_impedance.I.series.values;
        idx_fault = t > 0.045 & t < 0.049;
        Irms_fault = sqrt(mean(I(idx_fault,:).^2,1));
        ratio = Irms_fault ./ max(Irms0, 1e-6);
        spiked = ratio > 1.5;
        fprintf('type=%2d  Irms=%-30s ratio=%-30s spiked_phase=%s\n', ...
            k, mat2str(round(Irms_fault,1)), mat2str(round(ratio,2)), mat2str(spiked));
    catch ME
        fprintf('type=%2d  仿真出错: %s\n', k, ME.message(1:min(60,end)));
    end
end

close_system(mdl, 0);
