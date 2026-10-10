// Mr Tharoor.app/Contents/MacOS/MrTharoor: runs `tharoor listen` as a child.
//
// macOS lists an Accessibility grant under the app responsible for the
// process. Started by launchd as plain Python, that was "python3.12". Started
// by this stub inside an app bundle, the child is the app's responsibility,
// so System Settings and the permission prompt say "Mr Tharoor".
//
// It only spawns argv[1..], forwards stop signals, and exits with the
// child's status, so launchd's KeepAlive sees exactly what the child did.

#include <errno.h>
#include <signal.h>
#include <spawn.h>
#include <stdio.h>
#include <sys/wait.h>

extern char **environ;
static pid_t child;

static void forward(int sig) {
    if (child > 0) kill(child, sig);
}

int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "usage: MrTharoor /path/to/command [args]\n");
        return 2;
    }
    signal(SIGTERM, forward);
    signal(SIGINT, forward);
    signal(SIGHUP, forward);
    if (posix_spawn(&child, argv[1], NULL, NULL, argv + 1, environ) != 0) {
        perror(argv[1]);
        return 127;
    }
    int status;
    while (waitpid(child, &status, 0) < 0) {
        if (errno != EINTR) return 1;
    }
    return WIFEXITED(status) ? WEXITSTATUS(status) : 128 + WTERMSIG(status);
}
