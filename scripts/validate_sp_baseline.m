mdl = 'feeder_SP';
outdir = 'D:\Desktop\故障定位\output';
open_system(fullfile(outdir, [mdl '.slx']));

fprintf('=== 编译检查 ===\n');
try
    set_param(mdl, 'SimulationCommand', 'update');
    fprintf('编译成功\n');
catch ME
    fprintf('编译失败,完整报告:\n%s\n', getReport(ME, 'extended', 'hyperlinks','off'));
    for k = 1:numel(ME.cause)
        fprintf('--- cause %d ---\n%s\n', k, getReport(ME.cause{k}, 'extended', 'hyperlinks','off'));
    end
end

set_param(mdl, 'StopTime', '0.06');
fprintf('\n=== 跑基线仿真(全部故障禁用) ===\n');
tic;
try
    simOut = sim(mdl, 'ReturnWorkspaceOutputs', 'on', 'SimscapeLogType', 'all');
    fprintf('仿真成功, 耗时 %.1f 秒\n', toc);
    slog = simOut.simlog;

    loads = readtable(fullfile(outdir,'node_loads.csv'), 'TextType','string');
    loads = loads(startsWith(loads.clean_id,'SP'),:);

    sample_ids = {'SP-0001','SP-0005','SP-0010','SP-0017','SP-0019'};
    fprintf('\n%-10s %-22s %-22s %-8s\n','节点','仿真Irms(A B C)','真实through_I(A B C)','比值(仿真/真实,平均)');
    for i = 1:numel(sample_ids)
        nid = sample_ids{i};
        blkname = ['L_' strrep(nid,'-','_')];
        try
            t = slog.(blkname).phase_splitter2.i_a.series.time;
            ia = slog.(blkname).phase_splitter2.i_a.series.values;
            ib = slog.(blkname).phase_splitter2.i_b.series.values;
            ic = slog.(blkname).phase_splitter2.i_c.series.values;
            idx = t > 0.03;
            Irms = [sqrt(mean(ia(idx).^2)) sqrt(mean(ib(idx).^2)) sqrt(mean(ic(idx).^2))];
        catch ME2
            fprintf('%s 取值失败: %s\n', nid, ME2.message(1:min(60,end)));
            continue
        end
        lrow = loads(loads.clean_id==nid,:);
        if height(lrow)==1
            real_I = [lrow.through_IA_A(1) lrow.through_IB_A(1) lrow.through_IC_A(1)];
            ratio = mean(Irms) / mean(real_I,'omitnan');
            fprintf('%-10s %-22s %-22s %.2f\n', nid, mat2str(round(Irms,2)), mat2str(round(real_I,2)), ratio);
        end
    end
catch ME3
    fprintf('仿真失败: %s\n', ME3.message);
end
close_system(mdl, 0);
