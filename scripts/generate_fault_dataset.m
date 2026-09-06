function generate_fault_dataset(linecode, csvdir, outdir, resistances, fault_types, node_limit)
% 对 feeder_<linecode> 模型批量注入故障(每次只启用一个Fault模块),
% 用 parsim 并行跑,每个场景导出:该线路所有监测点的三相电压/电流有效值
% (故障窗口内 vs 故障前基线),标签是故障发生的清洁编号。
% node_limit: 可选,只测前N个节点(小批量试跑用),不传则跑全部节点。

mdl = ['feeder_' linecode];
if ~bdIsLoaded(mdl)
    open_system(fullfile(outdir, [mdl '.slx']));
end

nodes = readtable(fullfile(csvdir, 'nodes.csv'), 'TextType', 'string');
nodes = nodes(startsWith(nodes.clean_id, linecode), :);
nodes = sortrows(nodes, 'depth');
all_node_ids = cellstr(nodes.clean_id);
if nargin >= 6 && ~isempty(node_limit)
    all_node_ids = all_node_ids(1:min(node_limit, numel(all_node_ids)));
end

FAULT_START = 0.04;
FAULT_DUR = 0.02;
set_param(mdl, 'StopTime', '0.07');
save_system(mdl);  % parsim要求模型在启动并行池前已保存(worker要从磁盘加载)

scenarios = {};
for ni = 1:numel(all_node_ids)
    for fi = 1:numel(fault_types)
        for ri = 1:numel(resistances)
            scenarios(end+1, :) = {all_node_ids{ni}, fault_types(fi), resistances(ri)}; %#ok<AGROW>
        end
    end
end
fprintf('%s: 共 %d 个场景(%d节点 x %d故障类型 x %d电阻档)\n', linecode, size(scenarios,1), ...
    numel(all_node_ids), numel(fault_types), numel(resistances));

simIn(1:size(scenarios,1)) = Simulink.SimulationInput(mdl);
for k = 1:size(scenarios,1)
    nid = scenarios{k,1};
    ft = scenarios{k,2};
    rv = scenarios{k,3};
    nid_safe = strrep(nid, '-', '_');
    fblk = [mdl '/F_' nid_safe];
    in = Simulink.SimulationInput(mdl);
    in = in.setBlockParameter(fblk, 'enable_temporal_fault', '1');
    in = in.setBlockParameter(fblk, 'fault_type_option', num2str(ft));
    in = in.setBlockParameter(fblk, 'R_pn_fault', num2str(rv));
    in = in.setBlockParameter(fblk, 'R_ng_fault', num2str(rv));
    in = in.setBlockParameter(fblk, 'fault_start_time', num2str(FAULT_START));
    in = in.setBlockParameter(fblk, 'fault_duration', num2str(FAULT_DUR));
    in = in.setModelParameter('SimscapeLogType', 'all');
    simIn(k) = in;
end

t0 = tic;
simOut = parsim(simIn, 'ShowProgress', 'on', 'TransferBaseWorkspaceVariables', 'off');
fprintf('parsim 全部完成, 耗时 %.1f 秒\n', toc(t0));

rows = {};
n_err = 0;
for k = 1:numel(simOut)
    if ~isempty(simOut(k).ErrorMessage)
        n_err = n_err + 1;
        continue
    end
    res = local_extract(simOut(k), all_node_ids, FAULT_START, FAULT_DUR);
    nid = scenarios{k,1};
    ft = scenarios{k,2};
    rv = scenarios{k,3};
    for j = 1:numel(all_node_ids)
        r = res(j);
        rows(end+1, :) = {linecode, nid, ft, rv, all_node_ids{j}, ...
            r.Ia_base, r.Ib_base, r.Ic_base, r.Va_base, r.Vb_base, r.Vc_base, ...
            r.Ia_fault, r.Ib_fault, r.Ic_fault, r.Va_fault, r.Vb_fault, r.Vc_fault}; %#ok<AGROW>
    end
end
if n_err > 0
    fprintf('警告: %d/%d 个场景仿真本身报错,已跳过\n', n_err, numel(simOut));
end

T = cell2table(rows, 'VariableNames', {'line','fault_node','fault_type','fault_R', ...
    'monitor_node','Ia_base','Ib_base','Ic_base','Va_base','Vb_base','Vc_base', ...
    'Ia_fault','Ib_fault','Ic_fault','Va_fault','Vb_fault','Vc_fault'});
outfile = fullfile(outdir, sprintf('sim_dataset_%s.csv', linecode));
writetable(T, outfile);
fprintf('已导出 %s (%d 行)\n', outfile, height(T));
end

function res = local_extract(out, node_ids, t_start, t_dur)
slog = out.simlog;
res = struct('Ia_base',{},'Ib_base',{},'Ic_base',{},'Va_base',{},'Vb_base',{},'Vc_base',{}, ...
             'Ia_fault',{},'Ib_fault',{},'Ic_fault',{},'Va_fault',{},'Vb_fault',{},'Vc_fault',{});
for j = 1:numel(node_ids)
    blkname = ['L_' strrep(node_ids{j}, '-', '_')];
    try
        ps = slog.(blkname).phase_splitter2;
        t = ps.i_a.series.time;
        ia = ps.i_a.series.values; ib = ps.i_b.series.values; ic = ps.i_c.series.values;
        Vmat = slog.(blkname).N2.V.series.values;  % Nx3, 列顺序对应 a,b,c
        va = Vmat(:,1); vb = Vmat(:,2); vc = Vmat(:,3);
        idx_base = t > 0.01 & t < t_start - 0.005;
        idx_fault = t > t_start + t_dur*0.3 & t < t_start + t_dur*0.9;
        rmsf = @(x,idx) sqrt(mean(x(idx).^2));
        res(j).Ia_base = rmsf(ia,idx_base); res(j).Ib_base = rmsf(ib,idx_base); res(j).Ic_base = rmsf(ic,idx_base);
        res(j).Va_base = rmsf(va,idx_base); res(j).Vb_base = rmsf(vb,idx_base); res(j).Vc_base = rmsf(vc,idx_base);
        res(j).Ia_fault = rmsf(ia,idx_fault); res(j).Ib_fault = rmsf(ib,idx_fault); res(j).Ic_fault = rmsf(ic,idx_fault);
        res(j).Va_fault = rmsf(va,idx_fault); res(j).Vb_fault = rmsf(vb,idx_fault); res(j).Vc_fault = rmsf(vc,idx_fault);
    catch
        res(j).Ia_base=NaN; res(j).Ib_base=NaN; res(j).Ic_base=NaN;
        res(j).Va_base=NaN; res(j).Vb_base=NaN; res(j).Vc_base=NaN;
        res(j).Ia_fault=NaN; res(j).Ib_fault=NaN; res(j).Ic_fault=NaN;
        res(j).Va_fault=NaN; res(j).Vb_fault=NaN; res(j).Vc_fault=NaN;
    end
end
end
