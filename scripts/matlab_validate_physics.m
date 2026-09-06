mdl = 'mini_v2';
open_system(fullfile(pwd, [mdl '.slx']));

srcblk = [mdl '/Source'];
loadblk = [mdl '/Load'];
faultblk = [mdl '/Fault'];
lineblk = [mdl '/Line'];

fprintf('=== 当前默认值 ===\n');
fprintf('load parameterization = %s\n', get_param(loadblk,'parameterization'));
fprintf('load component_structure_PQ = %s\n', get_param(loadblk,'component_structure_PQ'));
fprintf('fault fault_type_option = %s\n', get_param(faultblk,'fault_type_option'));
fprintf('fault enable_temporal_fault = %s\n', get_param(faultblk,'enable_temporal_fault'));

fprintf('\n=== 试探 parameterization 合法值(故意设错触发报错列表) ===\n');
try
    set_param(loadblk, 'parameterization', 'XXX_BAD_VALUE');
catch ME
    fprintf('%s\n', ME.message);
end
fprintf('\n=== 试探 fault_type_option 合法值 ===\n');
try
    set_param(faultblk, 'fault_type_option', 'XXX_BAD_VALUE');
catch ME
    fprintf('%s\n', ME.message);
end

% 设一个具体负荷: 100kW + 30kvar (大致对应 pf~0.96), 相电压基准 5.77kV
set_param(loadblk, 'VRated', '5.77e3');
set_param(loadblk, 'FRated', '50');
set_param(loadblk, 'P', '100e3');
set_param(loadblk, 'Qpos', '30e3');

% 故障:0.03s开始,持续0.02s, 电阻1欧姆(先用temporal方式,不管具体是哪个相别选项,等下用报错列表里挑一个)
set_param(faultblk, 'enable_temporal_fault', 'on');
set_param(faultblk, 'fault_start_time', '0.03');
set_param(faultblk, 'fault_duration', '0.02');
set_param(faultblk, 'R_pn_fault', '1');

set_param(mdl, 'StopTime', '0.08');
try
    simOut = sim(mdl, 'ReturnWorkspaceOutputs', 'on', 'SimscapeLogType', 'all');
    slog = simOut.simlog;
    t = slog.Load.wye_impedance.V.series.time;
    V = slog.Load.wye_impedance.V.series.values;   % 应该是 Nx3
    I = slog.Load.wye_impedance.I.series.values;
    fprintf('\nV size: %s, I size: %s\n', mat2str(size(V)), mat2str(size(I)));

    pre_idx = t < 0.02;
    fault_idx = t > 0.04 & t < 0.05;
    Vrms_pre = sqrt(mean(V(pre_idx,:).^2, 1));
    Irms_pre = sqrt(mean(I(pre_idx,:).^2, 1));
    Vrms_fault = sqrt(mean(V(fault_idx,:).^2, 1));
    Irms_fault = sqrt(mean(I(fault_idx,:).^2, 1));
    fprintf('故障前 Vrms(3相) = %s  (期望接近 5770 V 附近)\n', mat2str(round(Vrms_pre)));
    fprintf('故障前 Irms(3相) = %s  (期望 P/V/3~ 100e3/5770/... 量级几十安)\n', mat2str(round(Irms_pre,2)));
    fprintf('故障中 Vrms(3相) = %s\n', mat2str(round(Vrms_fault)));
    fprintf('故障中 Irms(3相) = %s  (期望明显变大,验证短路电流上升)\n', mat2str(round(Irms_fault,2)));
catch ME2
    fprintf('仿真失败: %s\n', ME2.message);
end

close_system(mdl, 0);
