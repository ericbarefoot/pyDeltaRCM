##  tools for water routing algorithms
##  refactored by eab
##  sep 2019

class water_tools(object):
    
    def update_flow_field(self, iteration):
        '''
        Update water discharge after one water iteration
        '''
        
        timestep = self._time
        
        dloc = (self.qxn**2 + self.qyn**2)**(0.5)
        
        qwn_div = np.ones((self.L,self.W))
        qwn_div[dloc>0] = self.qwn[dloc>0] / dloc[dloc>0]
        
        self.qxn *= qwn_div
        self.qyn *= qwn_div
        
        if timestep > 0:
            
            omega = self.omega_flow_iter
            
            if iteration == 0: omega = self.omega_flow
            
            self.qx = self.qxn*omega + self.qx*(1-omega)
            self.qy = self.qyn*omega + self.qy*(1-omega)
            
        else:
            self.qx = self.qxn.copy()
            self.qy = self.qyn.copy()
            
        self.qw = (self.qx**2 + self.qy**2)**(0.5)
        
        self.qx[0,self.inlet] = self.qw0
        self.qy[0,self.inlet] = 0
        self.qw[0,self.inlet] = self.qw0
        
    def update_velocity_field(self):
        '''
        Update the flow velocity field after one water iteration
        '''
        
        mask = (self.depth > self.dry_depth) * (self.qw > 0)
        
        self.uw[mask] = np.minimum(self.u_max, self.qw[mask] / self.depth[mask])
        self.uw[~mask] = 0
        self.ux[mask]= self.uw[mask] * self.qx[mask] / self.qw[mask]
        self.ux[~mask] = 0
        self.uy[mask]= self.uw[mask] * self.qy[mask] / self.qw[mask]
        self.uy[~mask] = 0
        
    def flooding_correction(self):
        '''
        Flood dry cells along the shore if necessary
        
        Check the neighbors of all dry cells. If any dry cells have wet
        neighbors, check that their stage is not higher than the bed elevation
        of the center cell.
        If it is, flood the dry cell.
        '''
        
        wet_mask = self.depth > self.dry_depth
        wet_mask_nh = self.get_wet_mask_nh()
        wet_mask_nh_sum = np.sum(wet_mask_nh, axis=0)
        
        # makes wet cells look like they have only dry neighbors
        wet_mask_nh_sum[wet_mask] = 0
        
        # indices of dry cells with wet neighbors
        shore_ind = np.where(wet_mask_nh_sum > 0)
        
        stage_nhs = self.build_weight_array(self.stage)
        eta_shore = self.eta[shore_ind]
        
        for i in range(len(shore_ind[0])):
            
            # pretends dry neighbor cells have stage zero
            # so they cannot be > eta_shore[i]
            
            stage_nh = wet_mask_nh[:,shore_ind[0][i],shore_ind[1][i]] * \
                stage_nhs[:,shore_ind[0][i],shore_ind[1][i]]
                
            if (stage_nh > eta_shore[i]).any():
                self.stage[shore_ind[0][i],shore_ind[1][i]] = max(stage_nh)
                
    def finalize_water_iteration(self, timestep, iteration):
        '''
        Finish updating flow fields
        Clean up at end of water iteration
        '''
        
        self.update_water(timestep, iteration)
        
        self.stage[:] = np.maximum(self.stage, self.H_SL)
        self.depth[:] = np.maximum(self.stage - self.eta, 0)
        
        self.update_flow_field(iteration)
        self.update_velocity_field()
        
    #############################################
    ################# water flow ################
    #############################################
    
    def init_water_iteration(self):
        
        self.qxn[:] = 0; self.qyn[:] = 0; self.qwn[:] = 0
        
        self.free_surf_flag[:] = 0
        self.indices[:] = 0
        self.sfc_visit[:] = 0
        self.sfc_sum[:] = 0
        
        self.pad_stage = np.pad(self.stage, 1, 'edge')
        
        self.pad_depth = np.pad(self.depth, 1, 'edge')
        
        self.pad_cell_type = np.pad(self.cell_type, 1, 'edge')
        
    def run_water_iteration(self):
        
        iter = 0
        start_indices = [self.random_pick_inlet(self.inlet) for x in range(self.Np_water)]
        
        self.qxn.flat[start_indices] += 1
        self.qwn.flat[start_indices] += self.Qp_water / self.dx / 2.
        
        self.indices[:,0] = start_indices
        current_inds = list(start_indices)
        
        self.looped[:] = 0
        
        while (sum(current_inds) > 0) & (iter < self.itmax):
            
            iter += 1
            
            self.check_size_of_indices_matrix(iter)
            
            inds = np.unravel_index(current_inds, self.depth.shape)
            inds_tuple = [(inds[0][i], inds[1][i]) for i in range(len(inds[0]))]
            
            new_cells = [self.get_weight(x)
                            if x != (0,0) else 4 for x in inds_tuple]
                            
            new_inds = list(map(lambda x,y: self.calculate_new_ind(x,y)
                            if y != 4 else 0, inds_tuple, new_cells))
                            
            dist = list(map(lambda x,y,z: self.step_update(x,y,z) if x > 0
                       else 0, current_inds, new_inds, new_cells))
                       
            new_inds = np.array(new_inds, dtype = np.int)
            new_inds[np.array(dist) == 0] = 0
            
            self.indices[:,iter] = new_inds
            
            current_inds = self.check_for_loops(new_inds, iter)
            
            current_inds = self.check_for_boundary(current_inds)
            
            self.indices[:,iter] = current_inds
            
            current_inds[self.free_surf_flag > 0] = 0
            
    def check_for_boundary(self, inds):
        
        self.free_surf_flag[(self.cell_type.flat[inds] == -1) & (self.free_surf_flag == 0)] = 1
        
        self.free_surf_flag[(self.cell_type.flat[inds] == -1) & (self.free_surf_flag == -1)] = 2
        
        inds[self.free_surf_flag == 2] = 0
        
        return inds
        
    def check_for_loops(self, inds, it):
        
        looped = [len(i[i>0]) != len(set(i[i>0])) for i in self.indices]
        
        for n in range(self.Np_water):
            
            ind = inds[n]
            # revised 'it' to 'np.max(it)' to match python 2 > assessment
            if (looped[n]) and (ind > 0) and (np.max(it) > self.L0):
                
                self.looped[n] += 1
                
                it = np.unravel_index(ind, self.depth.shape)
                
                px, py = it
                
                Fx = px - 1
                Fy = py - self.CTR
                
                Fw = np.sqrt(Fx**2 + Fy**2)
                
                if Fw != 0:
                    px = px + np.round(Fx / Fw * 5.)
                    py = py + np.round(Fy / Fw * 5.)
                    
                px = max(px, self.L0)
                px = int(min(self.L - 2, px))
                
                py = max(1, py)
                py = int(min(self.W - 2, py))
                
                nind = np.ravel_multi_index((px,py), self.depth.shape)
                
                inds[n] = nind
                
                self.free_surf_flag[n] = -1
                
        return inds
        
    def free_surf(self, it):
        '''calculate free surface after routing one water parcel'''
        
        
        Hnew = np.zeros((self.L,self.W))
        
        for n,i in enumerate(self.indices):
            
            inds = np.unravel_index(i[i > 0], self.depth.shape)
            xs, ys = inds
            
            Hnew[:] = 0
            
            if ((self.cell_type[xs[-1],ys[-1]] == -1) and
                (self.looped[n] == 0)):
                
                self.count += 1
                Hnew[xs[-1],ys[-1]] = self.H_SL
                #if cell is in ocean, H = H_SL (downstream boundary condition)
                
                it0 = 0
                
                for it in range(len(xs)-2, -1, -1):
                    #counting back from last cell visited
                    
                    i = int(xs[it])
                    ip = int(xs[it+1])
                    j = int(ys[it])
                    jp = int(ys[it+1])
                    dist = np.sqrt((ip-i)**2 + (jp-j)**2)
                    
                    if dist > 0:
                        
                        if it0 == 0:
                            
                            if ((self.uw[i,j] > self.u0 * 0.5) or
                                (self.depth[i,j] < 0.1*self.h0)):
                                #see if it is shoreline
                                
                                it0 = it
                                
                            dH = 0
                            
                        else:
                            
                            if self.uw[i,j] == 0:
                                
                                dH = 0
                                # if no velocity
                                # no change in water surface elevation
                                
                            else:
                                
                                dH = (self.S0 *
                                     (self.ux[i,j] * (ip - i) * self.dx +
                                      self.uy[i,j] * (jp - j) * self.dx) /
                                      self.uw[i,j])
                                      # difference between streamline and
                                      # parcel path
                                      
                    Hnew[i,j] = Hnew[ip,jp] + dH
                    #previous cell's surface plus difference in H
                    
                    self.sfc_visit[i,j] = self.sfc_visit[i,j] + 1
                    #add up # of cell visits
                    
                    self.sfc_sum[i,j] = self.sfc_sum[i,j] + Hnew[i,j]
                    # sum of all water surface elevations
                    
    def update_water(self,timestep,itr):
        '''update surface after routing all parcels
        could divide into 3 functions for cleanliness'''
        
        #####################################################################
        # update free surface
        #####################################################################
        
        Hnew = self.eta + self.depth
        Hnew[Hnew < self.H_SL] = self.H_SL
        #water surface height not under sea level
        
        Hnew[self.sfc_visit > 0] = (self.sfc_sum[self.sfc_visit > 0] /
                                    self.sfc_visit[self.sfc_visit > 0])
        #find average water surface elevation for a cell
        
        Hnew_pad = np.pad(Hnew, 1, 'edge')
        
        #smooth newly calculated free surface
        Htemp = Hnew
        
        for itsmooth in range(self.Nsmooth):
            
            Hsmth = Htemp
            
            for i in range(self.L):
                
                for j in range(self.W):
                    
                    if self.cell_type[i,j] > -2:
                        #locate non-boundary cells
                        
                        sumH = 0
                        nbcount = 0
                        
                        ct_ind = self.pad_cell_type[i-1+1:i+2+1, j-1+1:j+2+1]
                        Hnew_ind = Hnew_pad[i-1+1:i+2+1, j-1+1:j+2+1]
                        
                        Hnew_ind[1,1] = 0
                        Hnew_ind[ct_ind == -2] = 0
                        
                        sumH = np.sum(Hnew_ind)
                        nbcount = np.sum(Hnew_ind >0)
                        
                        if nbcount > 0:
                            
                            Htemp[i,j] = (self.Csmooth * Hsmth[i,j] +
                                          (1 - self.Csmooth) * sumH / nbcount)
                            #smooth if are not wall cells
                            
        Hsmth = Htemp
        
        if timestep > 0:
            self.stage = ((1 - self.omega_sfc) * self.stage +
                          self.omega_sfc * Hsmth)
                          
        self.flooding_correction()