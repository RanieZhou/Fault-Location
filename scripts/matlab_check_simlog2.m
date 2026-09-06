mdl = 'mini_v2';
open_system(fullfile(pwd, [mdl '.slx']));
set_param(mdl, 'StopTime', '0.1');
simOut = sim(mdl, 'ReturnWorkspaceOutputs', 'on', 'SimscapeLogType', 'all');
slog = simOut.simlog;

fprintf('class: %s\n', class(slog));
fprintf('=== methods ===\n');
disp(methods(slog));
fprintf('=== properties ===\n');
disp(properties(slog));

fprintf('\n=== Children (大写试试) ===\n');
try
    ch = slog.Children;
    for i = 1:numel(ch)
        fprintf('  %s\n', ch(i).Name);
    end
catch ME
    fprintf('fail: %s\n', ME.message);
end

close_system(mdl, 0);
