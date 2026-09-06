mdl = 'mini_v2';
open_system(fullfile(pwd, [mdl '.slx']));
set_param(mdl, 'StopTime', '0.1');
simOut = sim(mdl, 'ReturnWorkspaceOutputs', 'on', 'SimscapeLogType', 'all');
slog = simOut.simlog;
fprintf('=== simlog 顶层子项 ===\n');
disp(slog.children.Name);

fprintf('\n=== Load 节点下的子项 ===\n');
loadNode = slog.Load;
disp(loadNode.children.Name);

fprintf('\n=== 递归打印 Load 完整结构(2层) ===\n');
c1 = loadNode.children;
for i = 1:numel(c1)
    fprintf('  %s\n', c1(i).Name);
    try
        c2 = c1(i).children;
        for j = 1:numel(c2)
            fprintf('    %s\n', c2(j).Name);
        end
    catch
    end
end

fprintf('\n=== 试着取 Load 三相电压 (猜测路径) ===\n');
try
    va = slog.Load.L.v.series.values;
    fprintf('Load.L.v 最后一个值: %g\n', va(end));
catch ME
    fprintf('猜测路径失败: %s\n', ME.message);
end

close_system(mdl, 0);
