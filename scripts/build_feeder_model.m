function build_feeder_model(linecode, csvdir, outdir)
% 从 nodes.csv / edges_with_params.csv / node_loads.csv 里按 linecode('SP'或'HL')
% 筛出对应线路,程序化搭出完整的 Simscape Electrical 馈线模型:
%   电源 -> (每条边一个Transmission Line) -> 每个节点挂 Fault(默认禁用) + Load(如果有本地负荷)
% 所有中性点/地共用一个 Electrical Reference, 求解器用固定步长本地求解器(避开故障投切时的刚性问题)。

nodes = readtable(fullfile(csvdir, 'nodes.csv'), 'TextType', 'string');
edges = readtable(fullfile(csvdir, 'edges_with_params.csv'), 'TextType', 'string');
loads = readtable(fullfile(csvdir, 'node_loads.csv'), 'TextType', 'string');

nodes = nodes(startsWith(nodes.clean_id, linecode), :);
edges = edges(startsWith(edges.to_id, linecode), :);
loads = loads(startsWith(loads.clean_id, linecode), :);
nodes = sortrows(nodes, 'depth');

mdl = ['feeder_' linecode];
if bdIsLoaded(mdl)
    close_system(mdl, 0);
end
new_system(mdl);

eref = add_block('ee_lib/Connectors & References/Electrical Reference', [mdl '/Eref']);
set_param(eref, 'Position', [20 20 50 50]);
solver = add_block('nesl_utility/Solver Configuration', [mdl '/SolverCfg']);
set_param(solver, 'Position', [20 80 50 110]);
set_param(solver, 'UseLocalSolver', 'on');
set_param(solver, 'LocalSolverChoice', 'NE_BACKWARD_EULER_ADVANCER');
set_param(solver, 'LocalSolverSampleTime', '2e-5');

src = add_block('ee_lib/Sources/Voltage Source (Three-Phase)', [mdl '/SRC']);
set_param(src, 'Position', [100 20 140 60]);
set_param(src, 'vline_rms', '10e3');
set_param(src, 'freq', '50');
set_param(src, 'SShortCircuit', '100e6');
set_param(src, 'XR', '10');

erefPH = get_param(eref, 'PortHandles');
solverPH = get_param(solver, 'PortHandles');
srcPH = get_param(src, 'PortHandles');
add_line(mdl, erefPH.LConn(1), srcPH.LConn(1));
add_line(mdl, solverPH.RConn(1), erefPH.LConn(1));

node_port = containers.Map();
node_port('SOURCE') = srcPH.RConn(1);

ycursor = 20;
n_load = 0;
for i = 1:height(nodes)
    nid = char(nodes.clean_id(i));
    nid_safe = strrep(nid, '-', '_');  % Simulink块名/Simscape日志字段名不能含连字符
    parent_id = char(nodes.parent_clean_id(i));
    erow = edges(edges.from_id == parent_id & edges.to_id == nid, :);
    if height(erow) ~= 1
        error('找不到或找到多条边: %s -> %s (%d条)', parent_id, nid, height(erow));
    end

    ycursor = ycursor + 40;
    lineblk = add_block('ee_lib/Passive/Lines/Transmission Line (Three-Phase)', [mdl '/L_' nid_safe]);
    set_param(lineblk, 'Position', [220 ycursor 270 ycursor+30]);
    set_param(lineblk, 'Access_ground', 'off');
    len_km = max(erow.length_km_est(1), 0.05);
    set_param(lineblk, 'length', num2str(len_km));
    % edges_with_params.csv 存的是该区段的总量(正序r_ohm/x_ohm、零序r0_ohm/x0_ohm、
    % 正零序电容c1_uF/c0_uF),这里换算回"每公里"值,再按Transmission Line(Three-Phase)
    % 官方文档给的公式转成模块要的自感/互感参数:
    %   R=(2R1+R0)/3, Rm=(R0-R1)/3, L=(2L1+L0)/3, M=(L0-L1)/3, Cl=(C1-C0)/3, Cg=C0
    % 注意单位: R/Rm是Ohm/km, L/M是mH/km(不是H/km), Cl/Cg是uF/km(不是F/km)。
    r1_per_km = max(erow.r_ohm(1), 0.01) / len_km;
    x1_per_km = max(erow.x_ohm(1), 0.01) / len_km;
    r0_per_km = max(erow.r0_ohm(1), 0.01) / len_km;
    x0_per_km = max(erow.x0_ohm(1), 0.01) / len_km;
    l1_mH_per_km = x1_per_km / (2*pi*50) * 1000;
    l0_mH_per_km = x0_per_km / (2*pi*50) * 1000;
    c1_uF_per_km = erow.c1_uF(1) / len_km;
    c0_uF_per_km = erow.c0_uF(1) / len_km;

    R_self = (2*r1_per_km + r0_per_km) / 3;
    R_mutual = (r0_per_km - r1_per_km) / 3;
    L_self = (2*l1_mH_per_km + l0_mH_per_km) / 3;
    L_mutual = (l0_mH_per_km - l1_mH_per_km) / 3;
    Cl_val = (c1_uF_per_km - c0_uF_per_km) / 3;
    Cg_val = c0_uF_per_km;

    set_param(lineblk, 'R', num2str(R_self));
    set_param(lineblk, 'L', num2str(L_self));
    set_param(lineblk, 'M', num2str(L_mutual));
    set_param(lineblk, 'Rm', num2str(R_mutual));
    set_param(lineblk, 'Cl', num2str(max(Cl_val, 1e-5)));
    set_param(lineblk, 'Cg', num2str(max(Cg_val, 1e-5)));
    linePH = get_param(lineblk, 'PortHandles');

    parent_port = node_port(parent_id);
    add_line(mdl, parent_port, linePH.LConn(1), 'autorouting', 'on');
    node_port(nid) = linePH.RConn(1);

    faultblk = add_block('ee_lib/Utilities/Fault (Three-Phase)', [mdl '/F_' nid_safe]);
    set_param(faultblk, 'Position', [340 ycursor 380 ycursor+30]);
    set_param(faultblk, 'enable_temporal_fault', '0');
    set_param(faultblk, 'fault_type_option', '10');
    set_param(faultblk, 'R_pn_fault', '1');
    set_param(faultblk, 'R_ng_fault', '1');
    set_param(faultblk, 'fault_start_time', '0.5');
    set_param(faultblk, 'fault_duration', '0.02');
    faultPH = get_param(faultblk, 'PortHandles');
    add_line(mdl, node_port(nid), faultPH.LConn(1), 'autorouting', 'on');

    lrow = loads(loads.clean_id == nid, :);
    if height(lrow) == 1 && lrow.local_S_total_kVA(1) > 1
        n_load = n_load + 1;
        loadblk = add_block('ee_lib/Passive/RLC Assemblies/Wye-Connected Load', [mdl '/LD_' nid_safe]);
        set_param(loadblk, 'Position', [340 ycursor+40 380 ycursor+70]);
        set_param(loadblk, 'component_structure_PQ', 'ee.enum.rlc.structure.ParallelRLC');
        set_param(loadblk, 'VRated', '5.77e3');
        set_param(loadblk, 'FRated', '50');
        S = lrow.local_S_total_kVA(1) * 1e3;
        S = min(S, 400e3);  % 封顶,避免个别KCL反推噪声导致的离群大值把靠近电源的干线电流拉得过高
        pf = 0.9;
        Pv = S * pf;
        Qv = S * sin(acos(pf));
        set_param(loadblk, 'P', num2str(Pv));
        set_param(loadblk, 'Qpos', num2str(Qv));
        loadPH = get_param(loadblk, 'PortHandles');
        add_line(mdl, node_port(nid), loadPH.LConn(1), 'autorouting', 'on');
        add_line(mdl, loadPH.RConn(1), erefPH.LConn(1), 'autorouting', 'on');
    end
end

set_param(mdl, 'StopTime', '0.6');
save_system(mdl, fullfile(outdir, [mdl '.slx']));
fprintf('%s: %d 节点, %d 条边, %d 个负荷点, 已保存 %s.slx\n', linecode, height(nodes), height(edges), n_load, mdl);
close_system(mdl, 0);
end
