mdl = 'mini_v2';
open_system(fullfile(pwd, [mdl '.slx']));
set_param(mdl, 'StopTime', '0.1');
simOut = sim(mdl, 'ReturnWorkspaceOutputs', 'on', 'SimscapeLogType', 'all');
slog = simOut.simlog;

function explore(node, prefix, depth, maxdepth)
    if depth > maxdepth
        return
    end
    ids = node.childIds;
    for i = 1:numel(ids)
        c = node.child(ids{i});
        fprintf('%s%s\n', prefix, ids{i});
        explore(c, [prefix '  '], depth+1, maxdepth);
    end
end

fprintf('=== Load 子树(3层) ===\n');
explore(slog.Load, '  ', 1, 3);

fprintf('\n=== Source 子树(3层) ===\n');
explore(slog.Source, '  ', 1, 3);

fprintf('\n=== Line 子树(2层) ===\n');
explore(slog.Line, '  ', 1, 2);

fprintf('\n=== 用 find 搜全局变量名含 "v" 或 "i" 的叶子(前20个) ===\n');
try
    results = slog.find('id', 'v');
    fprintf('find id=v 数量: %d\n', numel(results));
catch ME
    fprintf('find失败: %s\n', ME.message);
end

close_system(mdl, 0);
