    /* Fork transport boundary: keep the original host continuation/root protocol.
     * CPU reference is explicit. Vulkan is rejected until its generated gate exists. */
    if (transport && fid_bangs((u32)term_aux(t))) {
      u32 fid = (u32)term_aux(t);
      if (fid_arity(fid) != 1 || (u32)H[tl + 1] != 0) {
        err_fail("fork: unsupported root task ABI");
      }
      Term cont = H[tl];
      u32 idx = (u32)(H[tl + 1] >> 32) & 0xFFFF;
      if (getenv("BEND_FORK_TRACE")) fprintf(stderr, "fork %s root=%u\n", transport, fid);
      rv[0] = strcmp(transport, "cpu-reference") == 0
        ? fork_reference(fid, (u32)H[term_loc(t)])
        : fork_vulkan(fid, (u32)H[term_loc(t)]);
      heap_free(e, cls_fit(3), term_loc(t));
      t = task_deliver(H, cont, idx, rv, 1);
      if (t == 0) break;
      continue;
    }
