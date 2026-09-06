mdl = 'feeder_SP';
outdir = 'D:\Desktop\故障定位\output';
if ~bdIsLoaded(mdl)
    open_system(fullfile(outdir, [mdl '.slx']));
end
set_param(mdl, 'StopTime', '0.03');
simOut = sim(mdl, 'ReturnWorkspaceOutputs', 'on', 'SimscapeLogType', 'all');
slog = simOut.simlog;
node = slog.L_SP_0001.phase_splitter2;
fprintf('phase_splitter2 子项: %s\n', strjoin(node.childIds, ', '));
fprintf('phase_splitter2.a 子项: %s\n', strjoin(node.a.childIds, ', '));
L = slog.L_SP_0001;
fprintf('L 顶层子项: %s\n', strjoin(L.childIds, ', '));
fprintf('class(L.N2) = %s, 子项: %s\n', class(L.N2), strjoin(L.N2.childIds, ', '));
fprintf('class(L.N2.V) = %s\n', class(L.N2.V));
try
    v2 = L.N2.V.series.values;
    fprintf('L.N2.V.series.values 大小: %s, 最后一行: %s\n', mat2str(size(v2)), mat2str(v2(end,:)));
catch ME
    fprintf('L.N2.V失败: %s\n', ME.message);
end
close_system(mdl, 0);
